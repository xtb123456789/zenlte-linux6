#!/usr/bin/env python3
import os, sys, time, termios, fcntl, select, glob, base64, hashlib

PORT = glob.glob('/dev/cu.usbmodem*')[0]
BAUD = termios.B115200
CHUNK = 2048

def open_port():
    fd = os.open(PORT, os.O_RDWR | os.O_NOCTTY | os.O_NONBLOCK)
    a = termios.tcgetattr(fd)
    a[0] = 0; a[1] = 0; a[3] = 0
    a[2] = termios.CS8 | termios.CREAD | termios.CLOCAL
    a[4] = BAUD; a[5] = BAUD
    a[6][termios.VMIN] = 0; a[6][termios.VTIME] = 0
    termios.tcsetattr(fd, termios.TCSANOW, a)
    # blocking
    fl = fcntl.fcntl(fd, fcntl.F_GETFL); fcntl.fcntl(fd, fcntl.F_SETFL, fl & ~os.O_NONBLOCK)
    return fd

def drain(fd, secs):
    fl = fcntl.fcntl(fd, fcntl.F_GETFL); fcntl.fcntl(fd, fcntl.F_SETFL, fl | os.O_NONBLOCK)
    buf=b""; end=time.time()+secs
    while time.time()<end:
        r,_,_=select.select([fd],[],[],0.2)
        if r:
            try: buf+=os.read(fd,65536)
            except OSError: pass
    fcntl.fcntl(fd, fcntl.F_SETFL, fl & ~os.O_NONBLOCK)
    return buf

def main():
    path = sys.argv[1]          # file to send (will be written as-is remotely)
    remote = sys.argv[2]        # remote target path
    data = open(path,'rb').read()
    b64 = base64.encodebytes(data).decode()
    fd = open_port()
    drain(fd, 0.5)
    print(">> syncing shell", flush=True)
    os.write(fd, b"\r"); time.sleep(0.4); drain(fd,0.5)
    os.write(fd, b"stty -echo\r"); time.sleep(0.4); drain(fd,0.3)
    start = f"base64 -d > {remote} << 'B64ZZEND'\n".encode()
    os.write(fd, start); time.sleep(0.5)
    print(f">> sending {len(b64)} base64 chars -> {remote}", flush=True)
    t0=time.time(); n=0
    for i in range(0, len(b64), CHUNK):
        os.write(fd, b64[i:i+CHUNK].encode())
        n += CHUNK
        sys.stdout.write(f"\r   {min(n,len(b64))}/{len(b64)}"); sys.stdout.flush()
        time.sleep(0.02)
    os.write(fd, b"B64ZZEND\n"); time.sleep(0.5)
    os.write(fd, b"stty echo\r"); time.sleep(0.3); drain(fd,0.3)
    print(f"\n>> sent in {time.time()-t0:.1f}s", flush=True)
    exp = hashlib.sha256(data).hexdigest()
    os.write(fd, f"sha256sum {remote}; echo EXPECT {exp}; echo B64_DONE\r".encode())
    buf=b""; end=time.time()+30
    while time.time()<end:
        buf+=drain(fd,0.5)
        if b"B64_DONE" in buf: break
    print(buf.decode(errors='replace')[-800:])
    os.close(fd)

if __name__ == "__main__":
    main()

import os, sys, termios, time, glob, select

dev = glob.glob('/dev/cu.usbmodem*')[0]
secs = float(sys.argv[1]) if len(sys.argv) > 1 else 30.0
fd = os.open(dev, os.O_RDWR | os.O_NOCTTY | os.O_NONBLOCK)
a = termios.tcgetattr(fd)
iflag, oflag, cflag, lflag, ispeed, ospeed, cc = a
iflag &= ~(termios.IGNBRK | termios.BRKINT | termios.PARMRK | termios.ISTRIP |
           termios.INLCR | termios.IGNCR | termios.ICRNL | termios.IXON)
oflag &= ~termios.OPOST
lflag &= ~(termios.ECHO | termios.ECHONL | termios.ICANON | termios.ISIG | termios.IEXTEN)
cflag &= ~(termios.CSIZE | termios.PARENB)
cflag |= termios.CS8 | termios.CREAD | termios.CLOCAL
termios.tcsetattr(fd, termios.TCSANOW, [iflag, oflag, cflag, lflag, ispeed, ospeed, cc])

end = time.time() + secs
while time.time() < end:
    r, _, _ = select.select([fd], [], [], 0.5)
    if r:
        try:
            d = os.read(fd, 65536)
        except BlockingIOError:
            continue
        if d:
            sys.stdout.write(d.decode('utf-8', 'replace'))
            sys.stdout.flush()
os.close(fd)

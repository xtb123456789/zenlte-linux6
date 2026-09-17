import sys, os, termios, time, glob, select
dev = glob.glob('/dev/cu.usbmodem*')[0]
fd = os.open(dev, os.O_RDWR | os.O_NOCTTY | os.O_NONBLOCK)
attrs = termios.tcgetattr(fd)
iflag,oflag,cflag,lflag,ispeed,ospeed,cc = attrs
iflag &= ~(termios.IGNBRK|termios.BRKINT|termios.PARMRK|termios.ISTRIP|termios.INLCR|termios.IGNCR|termios.ICRNL|termios.IXON)
oflag &= ~termios.OPOST
lflag &= ~(termios.ECHO|termios.ECHONL|termios.ICANON|termios.ISIG|termios.IEXTEN)
cflag &= ~(termios.CSIZE|termios.PARENB); cflag |= termios.CS8|termios.CREAD|termios.CLOCAL
termios.tcsetattr(fd, termios.TCSANOW, [iflag,oflag,cflag,lflag,ispeed,ospeed,cc])
DRAIN=float(os.environ.get('DRAIN','1.2'))
def drain(t):
    end=time.time()+t; b=b''
    while time.time()<end:
        r,_,_=select.select([fd],[],[],0.1)
        if r:
            try: d=os.read(fd,65536)
            except BlockingIOError: d=b''
            if not d: break
            b+=d; end=time.time()+0.3
    return b
os.write(fd,b'\r'); drain(1.0)
for c in sys.argv[1:]:
    os.write(fd,(c+'\r').encode()); time.sleep(0.3); sys.stdout.write(drain(DRAIN).decode('utf-8','replace'))
os.close(fd)

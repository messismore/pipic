#!/usr/bin/python

import Image
import os, sys, argparse
import subprocess
import time
import io, picamera
from fractions import Fraction
from datetime import datetime
from MergeHDRStack import MergeHDRStack

class timelapse:
    """
    Timelapser class.

    Options:
        `w` : Width of images.
        `h` : Height of images.
        `interval` : Interval of shots, in seconds.  Recommended minimum is 10s.
        `maxtime` : Maximum amount of time, in seconds, to run the timelapse for.
            Set to 0 for no maximum.
        `maxshots` : Maximum number of pictures to take.  Set to 0 for no maximum.
        `targetBrightness` : Desired brightness of images, on a scale of 0 to 255.
        `maxdelta` : Allowed variance from target brightness.  Discards images that
            are more than `maxdelta` from `targetBrightness`.  Set to 256 to keep
            all images.
        `iso` : ISO used for all images.

    Once the timelapser is initialized, use the `findinitialparams` method to find
    an initial value for shutterspeed to match the targetBrightness.

    Then run the `timelapser` method to initiate the actual timelapse.

    EXAMPLE::
        T=timelapse()
        T.timelapser()

    The timelapser broadcasts zmq messages as it takes pictures.
    The `listen` method sets up the timelapser to listen for signals from 192.168.0.1,
    and take a shot when a signal is received.

    EXAMPLE::
        T=timelapse()
        T.listen()
    """
    def __init__(self, nodelete=False, w=1920, h=1080, interval=15, maxtime=0, maxshots=0,
                 targetBrightness=100, maxdelta=256, iso=100,
                 colourbalance='133/64' '337/256', hdr=60):
        self.camera=picamera.PiCamera()
        self.camera.framerate = 10

        self.w=w
        self.h=h
        self.camera.resolution = (w, h)
        self.iso=iso
        self.camera.iso=iso
        self.interval=interval
        self.maxtime=maxtime
        self.maxshots=maxshots
        self.targetBrightness=targetBrightness
        self.maxdelta=maxdelta
        self.colourbalance=colourbalance
        # hdr can be set to an integer from 0 to 25. If > 0, two additional
        # pictures will be taken, with hdr as exposure compensation
        self.hdr=hdr
        self.nodelete = nodelete

        #metersite is one of 'c', 'a', 'l', or 'r', for center, all, left or right.
        #Chooses a region of the image to use for brightness measurements.
        self.metersite='c'

        #Setting the maxss under one second prevents flipping into a slower camera mode.
        #self.maxss=1500000
        self.maxss=999000
        self.minss=100
        self.floatToSS = lambda x : max(min(int(self.minss+(self.maxss-self.minss)*x), self.maxss), self.minss)
        self.SSToFloat = lambda ss : max(min((float(ss)-self.minss)/(self.maxss-self.minss),1.0),0.0)

        #Brightness data caching.
        self.brightwidth=20
        self.brData=[]
        self.brindex=0
        self.lastbr=0
        self.avgbr=0
        self.shots_taken=0

        print 'Finding initial SS....'
        # Give the camera's auto-exposure and auto-white-balance algorithms
        # some time to measure the scene and determine appropriate values
        time.sleep(1)
        # This capture discovers initial AWB and SS.
        self.camera.capture('try.jpg')
        self.camera.shutter_speed = self.camera.exposure_speed
        self.currentss=self.camera.exposure_speed
        self.camera.exposure_mode = 'off'

        if self.colourbalance is not 'auto':  # '497/256', '177/128'
            self.camera.awb_mode = 'off'
            self.camera.awb_gains = Fraction(27, 16), Fraction(103, 64)
            print 'preset WB: ', self.camera.awb_gains
        else:
            self.wb_gains = self.camera.awb_gains
            print 'auto WB: ', self.wb_gains
            print type(self.wb_gains)
            file = open("whitebalance.txt", "w")
            file.write(str(self.wb_gains))
            file.close()
            self.camera.awb_mode = 'off'
            self.camera.awb_gains = self.wb_gains

        self.findinitialparams()
        print "Set up timelapser with: "
        print "\tmaxtime :\t", self.maxtime
        print "\tmaxshots:\t", self.maxshots
        print "\tinterval:\t", self.interval
        print "\tBrightns:\t", self.targetBrightness
        print "\tSize    :\t", self.w, 'x', self.h

    def __repr__(self):
        return 'A timelapse instance.'

    def avgbrightness(self, im):
        """
        Find the average brightness of the provided image according to the method
        defined in `self.metersite`.  `im` should be a PIL image.
        """
        meter=self.metersite
        aa=im.convert('L') # convert to black and white
        (h,w)=aa.size

        # This seems to mess up historgram() to return garbled data
        #
        # if meter=='c':
        #     top=int(1.0*h/2-.15*h)+1
        #     bottom=int(1.0*h/2+.15*h)-1
        #     left=int(1.0*w/2-.15*w)+1
        #     right=int(1.0*w/2+.15*w)+1
        # elif meter=='l':
        #     top=int(1.0*h/2-.15*h)+1
        #     bottom=int(1.0*h/2+.15*h)-1
        #     left=0
        #     right=int(.3*w)+2
        # elif meter=='r':
        #     top=int(1.0*h/2-.15*h)+1
        #     bottom=int(1.0*w/2+.15*w)-1
        #     left=h-int(.3*w)-2
        #     right=w
        # else:
        #     top=0
        #     bottom=h
        #     left=0
        #     right=w
        # aa=aa.crop((left,top,right,bottom))
        pixels=(aa.size[0]*aa.size[1])
        h=aa.histogram()
        mu0=1.0*sum([(i+1)*h[i] for i in range(len(h))])/pixels
        if sum(h[245:255]) > pixels * 0.05:
            print (sum(h[245:255])*100/pixels), "%% of image overexposed! Adding penalty..."
            mu0 = mu0 + 10
            if mu0 > 255: mu0 = 255
        return round(mu0,2)

    def dynamic_adjust(self, gamma=0.2):
        """
        Applies a simple gradient descent to try to correct shutterspeed and
        brightness to match the target brightness.
        """
        delta=self.targetBrightness-self.lastbr
        #Adj = lambda v: math.log( math.exp(v)*(1.0+1.0*delta*gamma/self.targetBrightness) )
        Adj = lambda v: v*(1.0+1.0*delta*gamma/self.targetBrightness)
        x=self.SSToFloat(self.currentss)
        if x<=0.001: x=0.01
        x=Adj(x)
        self.currentss=self.floatToSS(x)
        #Find an appropriate framerate.
        #For low shutter speeds, ths can considerably speed up the capture.
        # FR=Fraction(9*1000000,10*self.currentss)
        # if FR>15: FR=15
        # if FR<0.1: FR=Fraction(1,10)
        # self.camera.framerate=FR

    def capture(self):
        """
        Take a picture, returning a PIL image.
        """
        # Create the in-memory stream
        stream = io.BytesIO()
        self.camera.ISO=self.iso
        self.camera.shutter_speed=self.currentss
        # x=self.SSToFloat(self.currentss)
        capstart=time.time()
        self.camera.capture(stream, format='jpeg')
        capend=time.time()
        print 'Exp: %d\tFR: %f\t Capture Time: %f' % (self.camera.exposure_speed, round(float(self.camera.framerate),2), round(capend-capstart,2) )
        # "Rewind" the stream to the beginning so we can read its content
        stream.seek(0)
        image = Image.open(stream)
        return image

    def capture_hdr(self):
        """
        Take an additional under- and overexposed image.
        """
        initialss = self.currentss
        compensation = int(self.currentss * (self.hdr/100))
        print self.currentss, self.hdr/100
        self.currentss = initialss - compensation
        print self.camera.shutter_speed
        imunder = self.capture()
        self.currentss = initialss + compensation
        print self.camera.shutter_speed
        imover = self.capture()
        self.currentss = initialss
        print self.camera.shutter_speed


        images = (imunder, imover)
        return images

    def findinitialparams(self):
        """
        Take a number of small shots in succession to determine a shutterspeed
        and ISO for taking photos of the desired brightness.
        """
        killtoken=False
        while abs(self.targetBrightness-self.lastbr)>4:
            im=self.capture()
            self.lastbr=self.avgbrightness(im)
            self.avgbr=self.lastbr

            #Dynamically adjust ss and iso.
            self.dynamic_adjust(gamma=2.5)
            x=self.SSToFloat(self.currentss)
            print 'ss, x, br:\t', self.currentss, round(x,2), round(self.lastbr,2)
            if x>=1.0:
                x=1.0
                if killtoken==True:
                    break
                else:
                    killtoken=True
            elif x<=0.0:
                x=0.0
                if killtoken==True:
                    break
                else:
                    killtoken=True
        return True

    def maxxedbrightness(self):
        """
        Check whether we've reached maximum SS and ISO.
        """
        return (self.currentss==self.maxss)

    def minnedbrightness(self):
        """
        Check whether we've reached minimum SS and ISO.
        """
        return (self.currentss==self.minss)


    def shoot(self,filename=None,ss_adjust=True):
        """
        Take a photo and save it at a specified filename.
        """
        im=self.capture()
        #Saves file without exif and raster data; reduces file size by 90%,
        if filename!=None:
            try:
                im.save(filename)
            except:
                os.mkdir('/media/Usb-Drive/Timelapse/{:%Y-%m-%d}'.format(datetime.now()))
        if self.hdr != 0:
            ims = self.capture_hdr()
            filename = filename.replace('.jpg', '')
            ims[0].save(filename + '_under.jpg')
            ims[1].save(filename + '_over.jpg')

            filenames = [filename + '.jpg',
                         filename + '_under.jpg',
                         filename + '_over.jpg']

            MergeHDRStack(filenames, filename + '_HDR.jpg')
            if self.nodelete is not True:
                for x in filenames[1:]:
                    try:
                        os.remove(x)
                    except OSError, e:
                        print ("Error: %s - %s." % (e.filename,e.strerror))
            filename = filename + '.jpg'

        if not ss_adjust: return None

        self.lastbr=self.avgbrightness(im)
        if len(self.brData)==self.brightwidth:
            self.brData[self.brindex%self.brightwidth]=self.lastbr
        else:
            self.brData.append(self.lastbr)

        #Dynamically adjust ss and iso.
        self.avgbr=sum(self.brData)/len(self.brData)
        self.dynamic_adjust()
        self.shots_taken+=1
        self.brindex=(self.brindex+1)%self.brightwidth

        delta=self.targetBrightness-self.lastbr
        #if abs(delta)>self.maxdelta and not (maxxedbr or minnedbr):
        if abs(delta)>self.maxdelta:
            #Too far from target brightness.
            self.shots_taken-=1
            os.remove(filename)


    def timelapser(self):
        """
        Takes pictures at specified interval.
        """
        start_time=time.time()
        elapsed=time.time()-start_time

        while (elapsed<self.maxtime or self.maxtime==-1) and (self.shots_taken<self.maxshots or self.maxshots==-1):
            loopstart=time.time()
            dtime=subprocess.check_output(['date', '+%y%m%d_%T']).strip()
            dtime=dtime.replace(':', '.')
            #Broadcast options for this picture on zmq.
            command='0 shoot {} {} {} {}'.format(self.w, self.h, self.currentss, dtime)

            #Take a picture.
            filename='/media/Usb-Drive/Timelapse/{:%Y-%m-%d/%Y-%m-%d-%H-%M-%S}.jpg'.format(datetime.now())
            self.shoot(filename=filename)

            loopend=time.time()
            x=self.SSToFloat(self.currentss)
            print 'SS: ', self.currentss, '\tX:', round(x,2), '\tBR: ', self.lastbr, '\tShots:', self.shots_taken, '\tT:', round(loopend-loopstart,1)

            #Wait for next shot.
            time.sleep(max([0,self.interval-(loopend-loopstart)]))


#-------------------------------------------------------------------------------


def main(argv):


    parser = argparse.ArgumentParser(description='Timelapse tool for the Raspberry Pi.')
    parser.add_argument('--nodelete', action='store_true', help='Do not delete'
                        ' work files.')
    parser.add_argument('-W', '--width', default=1920, type=int, help='Set image width.' )
    parser.add_argument('-H', '--height', default=1080, type=int, help='Set image height.' )
    parser.add_argument('-i', '--interval', default=15, type=int, help='Set photo interval in seconds.  \nRecommended miniumum is 6.' )
    parser.add_argument('-t', '--maxtime', default=-1, type=int, help='Maximum duration of timelapse in minutes.\nDefault is -1, for no maximum duration.' )
    parser.add_argument('-n', '--maxshots', default=-1, type=int, help='Maximum number of photos to take.\nDefault is -1, for no maximum.' )
    parser.add_argument('-b', '--brightness', default=128, type=int, help='Target average brightness of image, on a scale of 1 to 255.\nDefault is 128.' )
    parser.add_argument('-d', '--delta', default=128, type=int, help='Maximum allowed distance of photo brightness from target brightness; discards photos too far from the target.  This is useful for autmatically discarding late-night shots.\nDefault is 128; Set to 256 to keep all images.' )
    parser.add_argument('-m', '--metering', default='a', type=str, choices=['a','c','l','r'], help='Where to average brightness for brightness calculations.\n"a" measures the whole image, "c" uses a window at the center, "l" meters a strip at the left, "r" uses a strip at the right.' )
    parser.add_argument('-I', '--iso', default=100, type=int, help='Set ISO.')
    parser.add_argument('-c', '--colourbalance', nargs=2, default='133/64' '337/256',
                        type=str, help='Set white balance as red and blue. '
                                       '''\nEg. \'493/256\' '387/256\' ''')
    parser.add_argument('-r', '--hdr', default=60, type=float,
                        help='Take two additional images, one under-, one '
                               'overexposed. \n Set this from 1 to 25,'
                               'depending the desired difference in exposure')


    args=parser.parse_args()
    if args.nodelete:
        nodelete = True
    else:
        nodelete = False

    TL = timelapse(nodelete, w=args.width, h=args.height, interval=args.interval,
                   maxshots=args.maxshots, maxtime=args.maxtime,
                   targetBrightness=args.brightness, maxdelta=args.delta,
                   iso=args.iso, colourbalance=args.colourbalance,
                   hdr=args.hdr)

    try:
        os.listdir('/media/Usb-Drive/Timelapse/')
    except:
        os.mkdir('/media/Usb-Drive/Timelapse')

    TL.timelapser()

    return True

#-------------------------------------------------------------------------------

if __name__ == "__main__":
   main(sys.argv[1:])

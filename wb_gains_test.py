import picamera
import time
from fractions import Fraction


camera = picamera.PiCamera()
camera.framerate = 10


time.sleep(1)
# This capture discovers initial AWB and SS.
camera.capture('try.jpg')
camera.shutter_speed = camera.exposure_speed
currentss = camera.exposure_speed
camera.exposure_mode = 'off'
camera.resolution = (1920, 1080)
camera.awb_mode = 'off'
camera.awb_gains = (4, 4)

print camera.awb_gains

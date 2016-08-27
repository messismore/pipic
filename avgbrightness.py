from PIL import Image


def avgbrightness(im):
    """
    Find the average brightness of the provided image according to the method
    defined in `self.metersite`.  `im` should be a PIL image.
    """
    aa=im.convert('L') # convert to black and white
    (h,w)=aa.size
    pixels=(aa.size[0]*aa.size[1])
    h=aa.histogram()
    print h
    mu0=1.0*sum([(i+1)*h[i] for i in range(len(h))])/pixels
    if sum(h[245:255]) > pixels * 0.05:
        print 'mu0: ', mu0
        mu0 = mu0 + 10
        print 'mu0: ', mu0
    print sum(h[245:255]), pixels * 0.05
    return round(mu0,2)
#
# pic = Image.open('histogram.jpg')
# pic = Image.open('histogram2.jpg')
pic = Image.open('histogram3.jpg')

print avgbrightness(pic)

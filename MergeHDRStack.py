from subprocess import call

def MergeHDRStack(filenames, image_name=None):
    """
    Create an HDR image.

    Receives a list of filenames and passes them to enfuse
    in order to create a high dynamic range image
    """
    call(['enfuse', '--output=%s' % (image_name), filenames[0], filenames[1], filenames[2]])
    return True

filenames = ['/Users/Felix/Documents/Github/pipic/enfuse/normal.jpg',
             '/Users/Felix/Documents/Github/pipic/enfuse/over.jpg',
             '/Users/Felix/Documents/Github/pipic/enfuse/under.jpg']

MergeHDRStack(filenames, 'Output.jpg')

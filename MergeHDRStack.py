from subprocess import call

def MergeHDRStack(filenames, image_name=None):
    """
    Create an HDR image.

    Receives a list of filenames and passes them to enfuse
    in order to create a high dynamic range image
    """
    filenames = ', '.join(filenames)
    call(['enfuse', '--output=%s' % (image_name), filenames])
    return True

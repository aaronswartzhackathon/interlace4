from freud import psychotherapist

import os
import sys

APPNAME = os.getenv("INTERLACE_APPNAME", "interlace")
PORT = int(os.getenv("INTERLACE_PORT", "5995"))

# Introspect to determine basedir and executable 
# (no clear way to refactor these checks out)
if getattr(sys, 'frozen', False):
    # eg we are running in a `PyInstaller' bundle
    basedir = sys._MEIPASS
    exepath = '"%s"' % (sys.executable)
else:
    # we are running in a normal Python environment
    basedir = os.path.abspath(os.path.dirname(__file__))
    exepath = '"%s" "%s"' % (sys.executable, os.path.abspath(__file__))

class InterLace(psychotherapist.CouchTherapy):
    pass

if __name__=='__main__':
    if len(sys.argv) == 1:
        # Subprocess CouchDB and make a GUI
        from PyQt4 import QtGui
        from freud import gui

        app = QtGui.QApplication(sys.argv)
        app.setApplicationName(APPNAME)
        p = psychotherapist.init(basedir, exepath, name=APPNAME, port=PORT)
        creds = psychotherapist.get_psychotherapist_creds(os.path.join(os.getenv("HOME"), ".freud", APPNAME, "conf"))
        main = gui.get_main_window(creds, port=PORT)
        app.exec_()
        p.kill()
        p.wait()

    elif sys.argv[1] == "sit-down":
        interlace = InterLace()
        try:
            interlace.run_forever()
        except Exception, err:
            import traceback
            for line in traceback.format_exc().split('\n'):
                psychotherapist.log(line)
            import time
            time.sleep(20)
            sys.exit(1)

    elif sys.argv[1] == "headless":
        # Subprocess CouchDB, but don't make a GUI
        p = psychotherapist.init(basedir, exepath, name=APPNAME, port=PORT)
        print "%s is running on port %d" % (APPNAME, PORT)
        p.wait()

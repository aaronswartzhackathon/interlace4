# import couchdb
from PyQt4 import QtGui

import freud.gui

class InterLaceGui(freud.gui.Office):
    def __init__(self, *a, **kw):
        kw["rootddoc"] = "internode"
        freud.gui.Office.__init__(self, *a, **kw)
        
        # self.screencastbutton = QtGui.QPushButton("start screencast")
        # self.toolbar.addWidget(self.screencastbutton)
        # self.screencast_process = None
        # self.screencastbutton.clicked.connect(self.toggle_screencast)

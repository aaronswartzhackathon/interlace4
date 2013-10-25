from freud import psychotherapist
import couchpotato
import ingest

import os
import sys

from twisted.web.server import Site
from twisted.web.resource import Resource
from twisted.internet import reactor

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

ingest.BASEDIR = basedir

class InterLace(psychotherapist.CouchTherapy):
    def __init__(self, streams):
        self.streams = streams
        psychotherapist.CouchTherapy.__init__(self)

    def doc_updated_type_uploaded_video(self, db, doc):
        if "upload" in doc.get("_attachments", {}):
            psychotherapist.log("upload processing started!")

            doc["type"] = "processing-video"
            db.save(doc)

            # Call in a thread so that our update calls go through and we can update the stream, &c
            reactor.callInThread(ingest.encode_from_upload, db, doc)
            #ingest.encode_from_upload(db, doc)

    def doc_updated_type_processing_video(self, db, doc):
        if "cluster-0" in doc.get("_attachments", {}):
            reactor.callFromThread(self.streams.dbs[db.name].update_stream, doc)

    def db_updated(self, db_name):
        psychotherapist.CouchTherapy.db_updated(self, db_name)

        if db_name not in self.streams.dbs:
            reactor.callFromThread(self.streams.add_database, self.server[db_name])

class DatabaseStreams(Resource):
    def __init__(self, db):
        Resource.__init__(self)
        self.db = db
        self.docs = {}          # _id -> CouchWebmResource

    def render_GET(self, req):
        return "streams for " + self.db.name

    def update_stream(self, doc):
        psychotherapist.log("update_stream", self.db.name, doc["_id"])

        if doc["_id"] not in self.docs:
            docstream = couchpotato.CouchWebMResource(self.db, doc)
            self.docs[doc["_id"]] = docstream
            self.putChild(doc["_id"], docstream)
            return
        docstream = self.docs[doc["_id"]]
        docstream.refresh(doc)

class AllOfTheStreams(Resource):
    def __init__(self):
        Resource.__init__(self)
        self.dbs = {}           # name -> DatabaseStreams

    def add_database(self, db):
        psychotherapist.log("add_database", db.name)

        dbstreams = DatabaseStreams(db)
        self.dbs[db.name] = dbstreams
        self.putChild(db.name, dbstreams)

        # Loop through all docs and add videos
        # XXX: using something like freud.js to keep docs in-memory would not be a bad idea...
        for doc_id in db:
            doc = db[doc_id]
            if doc.get("_attachments", {}).get("cluster-0"):
                dbstreams.update_stream(doc)

    def render_GET(self, req):
        return "all of the streams!"

def run_forever(interlace):
    try:
        interlace.run_forever()
    except Exception, err:
        import traceback
        for line in traceback.format_exc().split('\n'):
            psychotherapist.log(line)
        import time
        time.sleep(20)
        sys.exit(1)


if __name__=='__main__':
    if len(sys.argv) == 1:
        # Subprocess CouchDB and make a GUI
        from PyQt4 import QtGui

        import intergui

        app = QtGui.QApplication(sys.argv)
        app.setApplicationName(APPNAME)
        p = psychotherapist.init(basedir, exepath, name=APPNAME, port=PORT)
        creds = psychotherapist.get_psychotherapist_creds(os.path.join(os.getenv("HOME"), ".freud", APPNAME, "conf"))
        main = intergui.InterLaceGui(creds, port=PORT)
        main.show()
        app.exec_()
        p.kill()
        p.wait()

    elif sys.argv[1] == "sit-down":

        root = AllOfTheStreams()
        site = Site(root)
        reactor.listenTCP(5996, site)#, interface='0.0.0.0')

        interlace = InterLace(root)
        reactor.callInThread(run_forever, interlace)

        reactor.run()

    elif sys.argv[1] == "headless":
        # Subprocess CouchDB, but don't make a GUI
        p = psychotherapist.init(basedir, exepath, name=APPNAME, port=PORT)
        print "%s is running on port %d" % (APPNAME, PORT)
        p.wait()

from freud import psychotherapist
import couchpotato
import ingest

import json
import os
import urlparse
import requests
import sys

from twisted.web.server import Site
from twisted.web.resource import Resource
from twisted.internet import reactor, threads

APPNAME = os.getenv("INTERLACE_APPNAME", "interlace")
PORT = int(os.getenv("INTERLACE_PORT", "5995"))
SVC_PORT = int(os.getenv("INTERLACE_SVC_PORT", "5996"))

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

ingest.set_basedir(basedir)

def interlace_init(creds):
    # additionally, register twisted service
    psychotherapist.setconfig("http://localhost:%d" % (PORT), creds,
                              "httpd_global_handlers", "_stream", 
                              '{couch_httpd_proxy, handle_proxy_req, <<"http://localhost:%d">>}' % (SVC_PORT))

class InterLace(psychotherapist.CouchTherapy):
    def __init__(self, streams, *a, **kw):
        self.streams = streams
        psychotherapist.CouchTherapy.__init__(self, *a, **kw)

        self.svc_uri = self.server_uri.replace(str(PORT), str(SVC_PORT))

        # A node doesn't need multiple databases -- make sure this one exists.
        self.single_name = "localvideos"
        if not self.single_name in self.server:
            self.server.create(self.single_name)
            # force initialization
            self.db_created(self.single_name)

    def db_psychotherapist_doc_updated_type_relay_info(self, db, doc):
        # start replication
        if not "url" in doc:
            log("DPDUTRI", "no url in doc")
            return

        # rep_db = self.server["_replicator"]
        #
        # XXX: python-couchdb doesn't consider the _replicator
        # database to be valid. Ugh!
        # TODO: bug/patch/&c
        # 
        # /usr/lib/pymodules/python2.7/couchdb/client.pyc in validate_dbname(name)
        #    1073         return name
        #    1074     if not VALID_DB_NAME.match(name):
        # -> 1075         raise ValueError('Invalid database name')
        #    1076     return name
        # ValueError: Invalid database name

        # parsed = urlparse.urlparse(self.server_uri)
        # s_creds = (parsed.username, parsed.password)

        # Un-set old replication
        url = urlparse.urljoin(self.server_uri, "_replicator/master")
        res = requests.request("GET", url)
        if res.status_code > 400:
            rdoc = {"_id": "master"}
        else:
            rdoc = json.loads(res.text)

        d_url = url
        if "_rev" in rdoc:
            d_url += "?rev=%s" % (rdoc["_rev"])
        res = requests.request("DELETE", d_url)

        # Start replication
        ndoc = {
            "_id": "master",
            "source": self.single_name,
            "target": doc["url"],
            # "create_target": True, # XXX: for testing only
            "continuous": True}
        res = requests.request("PUT", url, data=json.dumps(ndoc))

    def doc_updated_type_uploaded_video(self, db, doc):
        if "upload" in doc.get("_attachments", {}):
            psychotherapist.log("upload processing started!")

            doc["type"] = "processing-video"
            db.save(doc)

            # Call in a thread so that our update calls go through and we can update the stream, &c
            reactor.callInThread(ingest.encode_from_upload, self, db, doc)
            #ingest.encode_from_upload(db, doc)

    def doc_updated_type_processing_video(self, db, doc):
        if "cluster-0" in doc.get("_attachments", {}):
            # Only refresh when the index *and* nclusters match in size
            if self.streams.dbs.get(db.name, None) and len(doc.get("index", [])) == len(filter(lambda x: x.startswith("cluster-"), doc["_attachments"].keys())):
                reactor.callFromThread(self.streams.dbs[db.name].update_stream, doc)

    def db_updated(self, db_name):
        if db_name.startswith("_"):
            return

        psychotherapist.CouchTherapy.db_updated(self, db_name)

        if db_name not in self.streams.dbs:
            if db_name in self.server and db_name != self.doctors_log:
                reactor.callFromThread(self.streams.add_database, self.server[db_name])
            else:
                psychotherapist.log("EEK! -- db not in server?", db_name)

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
        interlace_init((creds.split(":")[0], creds.split(":")[1][:-1]))
        main = intergui.InterLaceGui(creds, port=PORT)
        main.show()
        app.exec_()
        p.kill()
        p.wait()

    elif sys.argv[1] == "sit-down":

        root = AllOfTheStreams()
        site = Site(root)
        reactor.listenTCP(SVC_PORT, site)#, interface='0.0.0.0')

        interlace = InterLace(root)

        cmds = [(run_forever, [interlace], {}),
                (reactor.stop, [], {})] # will stop twisted service if run_forever fails
                #(reactor.callFromThread, [reactor.stop], {})]
        threads.callMultipleInThread(cmds)

        reactor.run()

    elif sys.argv[1] == "headless":
        # Subprocess CouchDB, but don't make a GUI
        p = psychotherapist.init(basedir, exepath, name=APPNAME, port=PORT)
        print "%s is running on port %d" % (APPNAME, PORT)
        p.wait()

    elif sys.argv[1] == "console":
        p = psychotherapist.init(basedir, exepath, name=APPNAME, port=PORT)
        creds = psychotherapist.get_psychotherapist_creds(os.path.join(os.getenv("HOME"), ".freud", APPNAME, "conf"))

        root = AllOfTheStreams()
        interlace = InterLace(root, server_uri="http://%slocalhost:%d" % (creds, PORT), basedir=basedir)

        import IPython
        IPython.embed()

        print "KILL"
        p.kill()
        p.wait()

import couchdb
import os
import socket
import subprocess
import urlparse

import chew
import streamrip.webm

from freud.psychotherapist import log

BASEDIR = "."
# eww!
def set_basedir(bd):
    global BASEDIR
    BASEDIR = bd
    # XXX
    chew.mininumm.BASEDIR = bd   

def encode(input_spec, chunksize=2**16):
    """input_spec tells ffmpeg how to find input
    Immediately yields a process handle, and from then on the generator gives data chunks
    (Admittedly the above is fairly wonky, but it helps avoid dealing with threading here...)"""

    cmd = ["./ffmpeg"] + input_spec + [
        # Encode with the InterLace encoding standard
        "-r", "25",
        "-vf", 'scale=trunc(oh*a/4)*4:320', # Force size to multiple of four.
        "-threads", "8",

        "-f", "webm",
        "-c:v", "libvpx",
        "-b:v", "250K",
        "-crf", "10",
        "-c:a", "libvorbis",
        "-"
    ]

    log(*cmd)

    p = subprocess.Popen(cmd, stdout=subprocess.PIPE, cwd=BASEDIR)
    yield p

    while True:
        chunk = p.stdout.read(chunksize)
        if len(chunk) == 0:
            return
        yield chunk

class WebMPieces(object):
    def __init__(self):
        self.queue = []
        self.chunks = []
    def registerProducer(self, *a):
        pass
    def finish(self):
        pass
    def write(self, buf):
        self.queue.append(buf)
    def empty(self):
        return len(self.queue) == 0
    def pop(self):
        chunk = self.queue.pop(0)
        self.chunks.append(chunk)
        return chunk

def clusters(datagenerator):
    parser = streamrip.webm.WebMParser()
    receiver = WebMPieces()
    parser.filterTo(receiver)

    for data in datagenerator:
        parser.write(data)
        while not receiver.empty():
            yield receiver.pop()
    # Don't forget the last cluster!
    parser.finish()
    while not receiver.empty():
        yield receiver.pop()

def _really_put_file_attachment(db, doc, filepath):
    # The error handling on _really_put_attachment doesn't work well
    # for file handles, because if it fails, the seekhead will be at
    # the end of the file and we'll get an empty attachment.
    doc = db[doc["_id"]]
    try:
        db.put_attachment(doc, open(filepath))
    except:
        log("another attachment errrrrr", filepath)
        doc = db[doc["_id"]]
        return _really_put_file_attachment(db, doc, filepath)

def _really_put_attachment(db, doc, *a, **kw):
    # XXX: This could be annoying for big uploads to oft-edited
    # documents. How to ameliorate? I think Couch allows putting
    # attachments without a _rev -- investigate.
    doc = db[doc["_id"]]
    try:
        db.put_attachment(doc, *a, **kw)
    except couchdb.ResourceConflict:
        return _really_put_attachment(db, doc, *a, **kw)
    except socket.error:
        log("SOCKET ERRRRRR")
        return _really_put_attachment(db, doc, *a, **kw)

def _really_set_field(db, doc, key, value):
    "returns (_id, _rev) if field was set through our doing, (_id, None) otherwise"
    doc = db[doc["_id"]]
    while doc.get(key) != value:
        doc[key] = value
        try:
            return db.save(doc)
        except couchdb.ResourceConflict:
            log("_really_set_field", "ResourceConflict", key)
            doc = db[doc["_id"]]
    return (doc["_id"], None)

def stream_to_couch(chunkgen, db, doc):
    index = []
    acc = ""
    for idx, cluster in enumerate(clusters(chunkgen)):

        if cluster.timestamp is None:
            cluster.timestamp = -1e9 # -1secs

        # Update the index first, so that if a cluster exists in the attachment, it is reflected in the index.
        # These two inserts should properly be atomic...
        index.append(float(cluster.timestamp) / 1e9) # -> seconds
        (new_id, new_rev) = _really_set_field(db, doc, "index", index)
        if new_rev is not None:
            doc["_rev"] = new_rev
        _really_put_attachment(db, doc, cluster.data, filename="cluster-%d" % (idx), content_type="application/octet-stream")

        acc += cluster.data

    # Post complete webm
    # XXX: Remove this once streamrip endpoint is deemed solid?
    # _really_put_attachment(db, doc, acc, filename="320p.webm", content_type="video/webm")
    # _really_set_field(db, doc, "type", "video")

def encode_from_upload(interlace, db, doc, upload_name="upload"):
    url = urlparse.urljoin(interlace.server_uri, "%s/%s/%s" % (db.name, doc["_id"], upload_name))
    chunkgen = encode(["-i", url])
    _p = chunkgen.next()        # process handle
    stream_to_couch(chunkgen, db, doc)

    # Generate chewing thumbnails
    # XXX: should run in parallel & share decode
    import tempfile
    dirname = tempfile.mkdtemp() + "/"

    chew.save_chewing(url, dirname)

    for filename in os.listdir(dirname):
        _really_put_file_attachment(db, doc, os.path.join(dirname, filename))
        os.unlink(os.path.join(dirname, filename))

    # _really_set_field(db, doc, "status", "complete")
    _really_set_field(db, doc, "type", "video")

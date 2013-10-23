import couchdb
import subprocess

import streamrip.webm

from freud.psychotherapist import log

BASEDIR = "."

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

def _really_put_attachment(db, doc, *a, **kw):
    # XXX: This could be annoying for big uploads to oft-edited
    # documents. How to ameliorate?
    try:
        db.put_attachment(doc, *a, **kw)
    except couchdb.ResourceConflict:
        doc = db[doc["_id"]]
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
        _really_put_attachment(db, doc, cluster.data, filename="cluster-%d" % (idx), content_type="application/octet-stream")

        if cluster.timestamp is None:
            cluster.timestamp = -1e9 # -1secs

        index.append(float(cluster.timestamp) / 1e9) # -> seconds
        acc += cluster.data
        (new_id, new_rev) = _really_set_field(db, doc, "index", index)
        if new_rev is not None:
            doc["_rev"] = new_rev

    # Post complete webm
    # XXX: Remove this once streamrip endpoint is deemed solid
    _really_put_attachment(db, doc, acc, filename="320p.webm", content_type="application/webm")
    _really_set_field(db, doc, "type", "video")

def encode_from_upload(db, doc, upload_name="upload"):
    import tempfile
    _fd, name = tempfile.mkstemp()
    # XXX: upload could be large -- stream instead of loading into memory
    open(name, 'w').write(db.get_attachment(doc, upload_name).read())
    chunkgen = encode(["-i", name])
    _p = chunkgen.next()        # process handle
    stream_to_couch(chunkgen, db, doc)

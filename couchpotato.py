# streaming video from couch
import streamrip.webm

from twisted.internet import interfaces
from twisted.python import log
from twisted.web import http, server
from zope.interface import implements

class CouchDBStreamProducer(object):
    implements(interfaces.IPullProducer)

    def __init__(self, db, doc, byte_offset=0, length=None):
        self.db = db
        self.doc = doc
        self.byte_offset = byte_offset
        self.length = length
        self._written = 0

        self._lengths = self.get_cluster_lengths()

    def streamTo(self, consumer):
        self.consumer = consumer
        consumer.registerProducer(self, False)

    def get_cluster_lengths(self):
        # Returns [size, size, size] for clusters in order
        clusters = self.doc["_attachments"].items()
        clusters = filter(lambda x: "cluster-" in x[0], clusters)
        clusters.sort(key=lambda x: int(x[0].split("-")[-1]))
        return [x[1]["length"] for x in clusters]

    def get_cluster_at_offset(self, offset):
        """returns binary data with (up to maxlen of) the cluster starting
        at or after offset"""
        cur_o = 0
        for idx, size in enumerate(self._lengths):
            if cur_o + size > offset:
                in_cluster_offset = offset - cur_o
                if in_cluster_offset > 0:
                    log.msg("strange -- starting within a cluster")
                return self.db.get_attachment(self.doc, "cluster-%d" % (idx)).read()[in_cluster_offset:]
            cur_o += size

    def resumeProducing(self):
        data = self.get_cluster_at_offset(self.byte_offset + self._written)

        if not data:
            self.consumer.unregisterProducer()
            self.consumer.finish()
        elif (self.length is not None and
              self._written + len(data) >= self.length):
            data = data[:self.length - self._written]
            self.consumer.write(data)
            self.consumer.unregisterProducer()
            self.consumer.finish()
        else:
            self.consumer.write(data)
            self._written += len(data)

    def stopProducing(self):
        pass

class CouchWebMResource(streamrip.webm.DynamicWebMResource):
    # Change backend of DynamicWebMResource to a CouchDB document with
    # cluster-%d blob-attachments.

    def __init__(self, db, doc):
        streamrip.webm.DynamicWebMResource.__init__(self, None, None)
        self.db = db
        self.doc = doc
        self.refresh()

    def refresh(self, doc=None):
        self.doc = doc or self.db[self.doc["_id"]]
        self.webm = streamrip.webm.DynamicWebM()

        clusters = self.doc.get("_attachments", {}).items()
        clusters = filter(lambda x: "cluster-" in x[0], clusters)
        clusters.sort(key=lambda x: int(x[0].split("-")[-1]))

        if len(clusters) == 0:
            raise IndexError, "No clusters or header yet"

        self.webm.parse_header(self.db.get_attachment(self.doc, "cluster-0").read())
        for idx, (name, stub) in enumerate(clusters[1:]):
            timestamp = self.doc["index"][idx + 1] # ignore header
            # XXX: timestamp right now is in seconds -- multiplying by 1000 / is that correct?
            self.webm.append_cluster(int(timestamp*1000), stub["length"])

    def _serve_everything(self, req, header, clusters_len):
        req.write(header)
        # We have our own header, thanks.
        # fh.seek(len(str(self.rip.get_header())))
        prod = CouchDBStreamProducer(self.db, self.doc,
                                     byte_offset=self.webm.orig_header_len,
                                     length=clusters_len)
        prod.streamTo(req)
        return server.NOT_DONE_YET

    def _serve_range(self, req, header, range, clusters_len):
        old_header_len = self.webm.orig_header_len
        new_header_len = len(header)
        virtual_len = new_header_len + clusters_len

        try:
            (start, end) = self._parse_range(range)
        except ValueError, e:
            print e
            req.setResponseCode(500)
            return str(e)

        if end is None:
            end = virtual_len
        else:
            end = min(end, virtual_len)

        req.setResponseCode(http.PARTIAL_CONTENT)
        req.setHeader(
            'content-range', 'bytes %d-%d/%d' % (
                start, end - 1, virtual_len))
        serve_bytes = end - start

        if start < new_header_len:
            data = header[start:end]
            req.write(data)
            header_bytes = len(data)
            serve_bytes -= header_bytes
            log.msg("range %r --> header %d+%d" % (
                range, start, header_bytes))
            start += header_bytes

        if end > new_header_len:
            file_start = start + old_header_len - new_header_len
            log.msg("range %r --> file %d+%d" % (
                range, file_start, serve_bytes))

            prod = CouchDBStreamProducer(self.db, self.doc,
                                         byte_offset=file_start,
                                         length=serve_bytes)
            prod.streamTo(req)
            return server.NOT_DONE_YET
        else:
            req.finish()
            return server.NOT_DONE_YET

    def _serve(self, req):
        # import pprint
        # pprint.pprint(dict(req.received_headers))
        req.setHeader('content-type', 'video/webm')
        req.setHeader('accept-ranges', 'bytes')
        req.setHeader('access-control-allow-origin', '*')

        duration = req.args.get("duration", [None])[0]
        if duration is not None:
            duration = float(duration)

        cluster_idx, clusters_len = self.webm.find_cluster(duration)
        if duration is None:
            if len(self.webm.clusters) != self.version:
                self.header = self.webm.get_header()
                self.version = len(self.webm.clusters)
            header = self.header
        else:
            header = self.webm.get_header(cluster_idx)

        req.setHeader('etag', '"%d"' % cluster_idx)
        virtual_len = len(header) + clusters_len
        # req.setHeader('content-length', str(virtual_len))
        range = req.getHeader('range')

        if range is not None:
            return self._serve_range(req, header, range, clusters_len)
        else:
            return self._serve_everything(req, header, clusters_len)

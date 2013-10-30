import json
import os
import sys

import numpy as np

import mininumm

PREFS = {
    "overview": {
        "row_t": 600,
        "row_w": 1200,
        "row_h": 72,
        "img_w": 50,
        "nrows": 10
        },
    "detail": {
        "row_t": 60,
        "row_w": 1200,
        "row_h": 72,
        "img_w": 72,
        "nrows": 10
        }
    }

class Chewer:
    def __init__(self, outdir, name, opts):
        self.outdir = outdir
        self.name = name
        self.opts = opts

        self.idx = 0
        self.frames = []

        # compute frame modulos
        self.frames_per_mosaic = int(
            self.opts["row_t"] * self.opts["nrows"] * self.opts["fps"])
        self.frames_per_incr_mosaic = int(
            self.opts["img_w"] * self.opts["fps"] * float(
                self.opts["row_t"]) / self.opts["row_w"])

        print "fpm", self.frames_per_mosaic
        print "fpim", self.frames_per_incr_mosaic

    def write(self, frame):
        # Assume frames are added pursuant with the opts framerate

        self.frames.append(frame)
        if len(self.frames) % self.frames_per_mosaic == 0:
            self.serialize()

    def close(self):
        self.serialize()

    def serialize(self, incremental=False):
        "writes the current self.frames to disk"

        outgen = self.assemble()
        still = outgen.next()
        mininumm.np2image(still,
                      os.path.join(
                          self.outdir, self.name + "-%06d.jpg" % (self.idx)))

        if not incremental:
            write_videos(outgen,
                         os.path.join(
                          self.outdir, self.name + "-%06d" % (self.idx)),
                         fps=self.opts["fps"],
                         ffopts=["-vb", "%dK" % (self.opts["fps"]*still.shape[1]/6)])
            
            self.frames = []
            self.idx += 1

    def assemble(self):
        frames = self.frames
        nrows = int(np.ceil(len(frames) / float(self.opts["fps"] * self.opts["row_t"])))
        n_output_frames = min(len(frames), self.opts["img_w"] - 1) # at most one loop
        print "assemble", n_output_frames, "frames", len(frames)

        # Yield the same np buffer every output frame
        out = np.zeros((self.opts["row_h"]*nrows, self.opts["row_w"], 3),
                          dtype=np.uint8)

        for idx in range(n_output_frames):
            # Always start from the top-left
            x = 0
            y = 0
            # But start from successive indices
            fr_idx = idx

            # w defines the width of a single image within the moving mosaic
            w = self.opts["img_w"]
            assert w <= frames[0].shape[1], "frames must be at least as wide as img_w"

            h = self.opts["row_h"]

            row_w = self.opts["row_w"]

            # frames are trimmed by starting at this x-location
            fr_ltrim = int((frames[x].shape[1]-w) / 2)

            while fr_idx < len(frames):
                out[y:y+h,x:x+w] = frames[fr_idx][:,fr_ltrim:fr_ltrim+w]

                x += w
                fr_idx += w

                if x+w > row_w:
                    y += h
                    x = 0
                if y >= out.shape[0]:
                    break

            yield out

def write_videos(gen, path, fps=30, ffopts=[]):
    fr = gen.next()
    p1 = mininumm.frame_writer(fr, path + '.webm', fps, ffopts)
    # p2 = mininumm.frame_writer(fr, path + '.tmp.mp4', fps, ffopts)

    for fr in gen:
        p1.stdin.write(fr.tostring())
        # p2.stdin.write(fr.tostring())

    p1.stdin.close()
    p1.wait()
    # p2.stdin.close()
    # p2.wait()

    # subprocess.call([
    #     "qt-faststart", path + ".tmp.mp4", path + ".mp4"])
    # os.unlink(path + ".tmp.mp4")

def save_chewing(src, rootpath=None):
    if rootpath is None:
        rootpath = src + "-"

    notes = mininumm.video_info(src)
    aspect = notes["width"]/float(notes["height"])
    chewers = []
    for name, opts in PREFS.items():

        # compute FPS
        opts["fps"] = float(opts["row_w"]) / opts["row_t"]

        chewers.append(Chewer(rootpath, name, opts))

    read_fps = max([X.opts["fps"] for X in chewers])
    read_h   = chewers[0].opts["row_h"]
    read_w = int(read_h*aspect)

    # Check that our manual fps controls will work
    for chew in chewers:
        if read_fps / chew.opts["fps"] != int(float(read_fps)/chew.opts["fps"]):
            raise AssertionError("invalid fps combo: %d & %d" % (read_fps, chew.opts["fps"]))
        if read_h != chew.opts["row_h"]:
            raise AssertionError("all heights must be the same")            

    # Capture video and feed to all of the chewers

    for idx,fr in enumerate(mininumm.video_frames(src, fps=read_fps, width=read_w, height=read_h)):
        for chew in chewers:
            if idx % (read_fps / chew.opts["fps"]) == 0:
                chew.write(fr)

    for chew in chewers:
        chew.close()

    json.dump(notes, open("%smeta.json" % (rootpath), 'w'))

def main():
    args = sys.argv[1:]

    if len(args) == 1:
        (inpt,) = args
        save_chewing(inpt)
    elif len(args) == 2:
        (inpt, root) = args
        save_chewing(inpt, root)
    else:
        raise ValueError

if __name__ == '__main__':
    main()


import numpy as np

class SimpleTracker:
    def __init__(self, max_lost=30, iou_thresh=0.3):
        self.next_id = 0
        self.tracks = {} # {id: {'box': [x1,y1,x2,y2], 'lost': 0, 'age_seconds': 0.0}}
        self.max_lost = max_lost
        self.iou_thresh = iou_thresh

    def update(self, detections, dt=0.1): 
        # detections: list of [x1, y1, x2, y2]
        
        # 1. Prediction (Optional: Kalman Filter) - Skip for simplicity
        
        # 2. Association (Greedy IoU Matching)
        updated_tracks = {}
        matched_track_ids = set()
        
        for i, det in enumerate(detections):
            best_iou = self.iou_thresh
            best_tid = -1
            
            for tid, trk in self.tracks.items():
                if tid in matched_track_ids: continue
                
                iou_val = self.compute_iou(det, trk['box'])
                if iou_val > best_iou:
                    best_iou = iou_val
                    best_tid = tid
            
            if best_tid != -1:
                # Update existing track
                trk = self.tracks[best_tid]
                trk['box'] = det
                trk['lost'] = 0
                trk['age_seconds'] += dt
                updated_tracks[best_tid] = trk
                matched_track_ids.add(best_tid)
            else:
                # Create new track
                self.next_id += 1
                updated_tracks[self.next_id] = {
                    'box': det,
                    'lost': 0,
                    'age_seconds': 0.0
                }
        
        # 3. Handle Lost Tracks
        for tid, trk in self.tracks.items():
            if tid not in matched_track_ids:
                trk['lost'] += 1
                if trk['lost'] < self.max_lost:
                    updated_tracks[tid] = trk
        
        self.tracks = updated_tracks
        return self.tracks

    def compute_iou(self, box1, box2):
        # box: [x1, y1, x2, y2]
        xA = max(box1[0], box2[0])
        yA = max(box1[1], box2[1])
        xB = min(box1[2], box2[2])
        yB = min(box1[3], box2[3])

        interArea = max(0, xB - xA) * max(0, yB - yA)
        box1Area = (box1[2] - box1[0]) * (box1[3] - box1[1])
        box2Area = (box2[2] - box2[0]) * (box2[3] - box2[1])
        
        unionArea = float(box1Area + box2Area - interArea)
        if unionArea == 0: return 0
        return interArea / unionArea

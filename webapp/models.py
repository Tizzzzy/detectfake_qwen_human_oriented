from . import db
from datetime import datetime


class QwenHumanOrientedGuess(db.Model):
    """One row per answered stimulus per participant, for the
    inference_raw_qwen_human_oriented.json stimulus pool (text + explanation): the
    human's AI-vs-Human decision."""
    __tablename__ = 'qwen_human_oriented_guess'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.String(150), index=True)
    trial_num = db.Column(db.Integer)             # 1-based position in this user's session
    stimulus_index = db.Column(db.Integer)        # 0-based position in the JSON array (stable id)
    text_id = db.Column(db.String(50))            # e.g. 'reddit_1024' -- NOT unique in the file
    occurrence = db.Column(db.Integer)            # 1-based rank among rows sharing this text_id
    text_path = db.Column(db.String(255))         # source path from the JSON's `text_path`
    label_truth = db.Column(db.String(10))        # 'Human' or 'AI', from the JSON's `label`
    guess = db.Column(db.String(10))              # 'Human' or 'AI'
    correct = db.Column(db.Boolean)
    ip = db.Column(db.String(150))
    user_platform = db.Column(db.String(150))
    user_browser = db.Column(db.String(150))
    user_version = db.Column(db.String(150))
    user_language = db.Column(db.String(150))
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)

    def __repr__(self):
        return f'<QwenHumanOrientedGuess {self.user_id} trial={self.trial_num} idx={self.stimulus_index}>'

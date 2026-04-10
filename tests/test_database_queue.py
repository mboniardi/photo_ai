"""
Test per database/queue.py — CRUD tabella analysis_queue.
"""
import pytest

PHOTO_DEFAULTS = {
    "file_path": "/mnt/nas/foto/test.jpg",
    "folder_path": "/mnt/nas/foto",
    "filename": "test.jpg",
    "format": "jpg",
    "file_size": 1024,
    "width": 100,
    "height": 100,
}


@pytest.fixture
def photo_id(tmp_db):
    from database.photos import insert_photo
    return insert_photo(tmp_db, **PHOTO_DEFAULTS)


class TestAddToQueue:
    def test_add_returns_queue_id(self, tmp_db, photo_id):
        from database.queue import add_to_queue
        qid = add_to_queue(tmp_db, photo_id=photo_id, priority=5)
        assert isinstance(qid, int) and qid > 0

    def test_default_status_is_pending(self, tmp_db, photo_id):
        from database.queue import add_to_queue, get_queue_item
        qid = add_to_queue(tmp_db, photo_id=photo_id)
        item = get_queue_item(tmp_db, qid)
        assert item["status"] == "pending"

    def test_default_priority_is_5(self, tmp_db, photo_id):
        from database.queue import add_to_queue, get_queue_item
        qid = add_to_queue(tmp_db, photo_id=photo_id)
        item = get_queue_item(tmp_db, qid)
        assert item["priority"] == 5


class TestGetNextPending:
    def test_returns_highest_priority_first(self, tmp_db):
        from database.photos import insert_photo
        from database.queue import add_to_queue, get_next_pending

        pid_low = insert_photo(tmp_db,
                               file_path="/mnt/a.jpg", folder_path="/mnt",
                               filename="a.jpg", format="jpg",
                               file_size=1, width=1, height=1)
        pid_high = insert_photo(tmp_db,
                                file_path="/mnt/b.jpg", folder_path="/mnt",
                                filename="b.jpg", format="jpg",
                                file_size=1, width=1, height=1)
        add_to_queue(tmp_db, photo_id=pid_low, priority=5)
        add_to_queue(tmp_db, photo_id=pid_high, priority=1)  # 1 = alta priorità

        item = get_next_pending(tmp_db)
        assert item["photo_id"] == pid_high

    def test_returns_none_when_empty(self, tmp_db):
        from database.queue import get_next_pending
        assert get_next_pending(tmp_db) is None

    def test_skips_non_pending(self, tmp_db, photo_id):
        from database.queue import add_to_queue, update_queue_status, get_next_pending
        qid = add_to_queue(tmp_db, photo_id=photo_id)
        update_queue_status(tmp_db, qid, "processing")
        assert get_next_pending(tmp_db) is None


class TestUpdateQueueStatus:
    def test_update_to_done(self, tmp_db, photo_id):
        from database.queue import add_to_queue, update_queue_status, get_queue_item
        qid = add_to_queue(tmp_db, photo_id=photo_id)
        update_queue_status(tmp_db, qid, "done")
        item = get_queue_item(tmp_db, qid)
        assert item["status"] == "done"

    def test_update_to_error_with_message(self, tmp_db, photo_id):
        from database.queue import add_to_queue, update_queue_status, get_queue_item
        qid = add_to_queue(tmp_db, photo_id=photo_id)
        update_queue_status(tmp_db, qid, "error", error_msg="timeout")
        item = get_queue_item(tmp_db, qid)
        assert item["status"] == "error"
        assert item["error_msg"] == "timeout"

    def test_increment_attempts(self, tmp_db, photo_id):
        from database.queue import add_to_queue, increment_attempts, get_queue_item
        qid = add_to_queue(tmp_db, photo_id=photo_id)
        increment_attempts(tmp_db, qid)
        increment_attempts(tmp_db, qid)
        item = get_queue_item(tmp_db, qid)
        assert item["attempts"] == 2


class TestResetProcessing:
    def test_resets_processing_to_pending(self, tmp_db, photo_id):
        from database.queue import add_to_queue, update_queue_status, \
            reset_stale_processing, get_queue_item
        qid = add_to_queue(tmp_db, photo_id=photo_id)
        update_queue_status(tmp_db, qid, "processing")
        reset_stale_processing(tmp_db)
        item = get_queue_item(tmp_db, qid)
        assert item["status"] == "pending"


class TestGetQueueStatus:
    def test_counts(self, tmp_db):
        from database.photos import insert_photo
        from database.queue import add_to_queue, update_queue_status, get_queue_counts

        for i in range(3):
            pid = insert_photo(tmp_db,
                               file_path=f"/mnt/img{i}.jpg",
                               folder_path="/mnt",
                               filename=f"img{i}.jpg",
                               format="jpg",
                               file_size=1, width=1, height=1)
            qid = add_to_queue(tmp_db, photo_id=pid)
            if i == 1:
                update_queue_status(tmp_db, qid, "done")
            if i == 2:
                update_queue_status(tmp_db, qid, "error")

        counts = get_queue_counts(tmp_db)
        assert counts["pending"] == 1
        assert counts["done"] == 1
        assert counts["error"] == 1

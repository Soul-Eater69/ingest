"""Tests for metrics collection and progress reporting."""

import json

from neo4j_ingest.metrics import JobMetrics, StepMetric, track_step


class TestStepMetric:
    def test_duration(self):
        s = StepMetric(name="test", start_time=100.0, end_time=102.5)
        assert s.duration_seconds == 2.5

    def test_records_per_second(self):
        s = StepMetric(name="test", records_processed=1000, start_time=100.0, end_time=110.0)
        assert s.records_per_second == 100.0

    def test_to_dict(self):
        s = StepMetric(name="test", status="completed", records_processed=5)
        d = s.to_dict()
        assert d["name"] == "test"
        assert d["status"] == "completed"
        assert d["records_processed"] == 5


class TestJobMetrics:
    def test_total_records(self):
        m = JobMetrics(job_id="abc")
        s1 = m.add_step("step1")
        s1.records_processed = 100
        s2 = m.add_step("step2")
        s2.records_processed = 200
        s2.records_failed = 5
        assert m.total_records_processed == 300
        assert m.total_records_failed == 5

    def test_to_json(self):
        m = JobMetrics(job_id="test123", status="completed")
        m.add_step("s1").records_processed = 10
        j = json.loads(m.to_json())
        assert j["job_id"] == "test123"
        assert j["status"] == "completed"
        assert len(j["steps"]) == 1


class TestTrackStep:
    def test_success(self):
        step = StepMetric(name="test")
        with track_step(step):
            pass
        assert step.status == "completed"
        assert step.start_time > 0
        assert step.end_time >= step.start_time

    def test_failure(self):
        step = StepMetric(name="test")
        with __import__("pytest").raises(ValueError):
            with track_step(step):
                raise ValueError("boom")
        assert step.status == "failed"
        assert step.error == "boom"

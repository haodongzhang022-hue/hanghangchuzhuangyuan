"""评审机制自动化测试：处置标签 + 代码检查器 + 自动打标"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../src"))

from hanghang.review import Disposition, dispose, parse_disposition, StandardChecker
from hanghang.review.auto_label import AutoLabelEngine


# ---------- Disposition 测试 ----------
def test_disposition_default():
    """默认兜底 proceed"""
    result = dispose()
    assert result.disposition == Disposition.MERGE  # 默认 severity=info → merge
    assert result.labels is not None


def test_disposition_severity_map():
    """严重级映射"""
    # hard/critical → fix_bug
    result = dispose(severity="hard")
    assert result.disposition == Disposition.FIX_BUG

    # warning → proceed
    result = dispose(severity="warning")
    assert result.disposition == Disposition.PROCEED

    # high_risk → consult
    result = dispose(severity="high_risk")
    assert result.disposition == Disposition.CONSULT


def test_disposition_trigger_map():
    """触发信号归一化"""
    # changes_requested → fix_bug
    result = dispose(severity="warning", trigger="changes_requested")
    assert result.disposition == Disposition.FIX_BUG

    # approved → merge
    result = dispose(severity="info", trigger="approved")
    assert result.disposition == Disposition.MERGE

    # needs_human → human
    result = dispose(severity="warning", trigger="needs_human")
    assert result.disposition == Disposition.HUMAN


def test_parse_disposition():
    """解析处置标签"""
    assert parse_disposition("merge") == Disposition.MERGE
    assert parse_disposition("fix_bug") == Disposition.FIX_BUG
    assert parse_disposition("proceed") == Disposition.PROCEED
    assert parse_disposition("invalid") is None


# ---------- StandardChecker 测试 ----------
def test_checker_good_code():
    """无问题代码通过"""
    with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
        f.write('"""test module"""\n\ndef test_func():\n    """Test function."""\n    return 42\n')
        tmpfile = f.name

    try:
        checker = StandardChecker(os.path.dirname(tmpfile))
        passed, issues = checker.check_file(tmpfile)
        assert passed is True
        assert len(issues) == 0
    finally:
        os.unlink(tmpfile)


def test_checker_todo():
    """TODO 注释硬失败"""
    with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
        f.write('"""test"""\n\n# TODO: fix this later\nx = 1\n')
        tmpfile = f.name

    try:
        checker = StandardChecker(os.path.dirname(tmpfile))
        passed, issues = checker.check_file(tmpfile)
        assert passed is False
        hard = [i for i in issues if i["severity"] == "hard"]
        assert len(hard) > 0
        assert any(i["rule"] == "todo_comment" for i in hard)
    finally:
        os.unlink(tmpfile)


def test_checker_debug_print():
    """src/ 下 debug print 硬失败"""
    with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
        f.write('"""test"""\n\ndef func():\n    print("debug")\n    return 1\n')
        tmpfile = f.name

    try:
        checker = StandardChecker(os.path.dirname(tmpfile))
        passed, issues = checker.check_file(tmpfile)
        # print 默认不算硬失败（只有 src/ 下才查 debug_print）
        assert passed is True
    finally:
        os.unlink(tmpfile)


# ---------- AutoLabelEngine 测试 ----------
def test_auto_label_issue_open():
    """Issue open → 打待处理标签"""
    with tempfile.TemporaryDirectory() as tmpdir:
        engine = AutoLabelEngine(os.path.join(tmpdir, "labels.jsonl"))
        result = engine.apply_event("issue.open", entity_id="ISSUE-1")
        assert result["action"] == "add"
        assert "待处理" in result["labels"]
        assert "P1" in result["labels"]


def test_auto_label_review_need_fix():
    """评审需修复 → 打需修复标签"""
    with tempfile.TemporaryDirectory() as tmpdir:
        engine = AutoLabelEngine(os.path.join(tmpdir, "labels.jsonl"))
        result = engine.apply_event("review.need_fix", entity_id="PR-1")
        assert result["action"] == "block"
        assert "需修复" in result["labels"]


def test_auto_label_review_pass():
    """评审通过 → 打适合合并标签"""
    with tempfile.TemporaryDirectory() as tmpdir:
        engine = AutoLabelEngine(os.path.join(tmpdir, "labels.jsonl"))
        result = engine.apply_event("review.pass", entity_id="PR-1")
        assert "评审通过" in result["labels"]


def test_disposition_overlap_signal():
    """重叠信号（merge+escalate）→ 取高介入 HUMAN，避免误判 merge"""
    result = dispose(severity="info", trigger="merge and escalate")
    assert result.disposition == Disposition.HUMAN

    # 纯 merge / approved → merge
    assert dispose(severity="info", trigger="approved").disposition == Disposition.MERGE
    assert dispose(severity="info", trigger="merge").disposition == Disposition.MERGE

    # 词边界：不因子串误命中（merged 不应命中 merge 判定外的信号）
    assert dispose(severity="info", trigger="merged request").disposition == Disposition.MERGE


def test_auto_label_progress_type_defense():
    """progress 为非数字时不应抛 ValueError，且不产生进度标签"""
    import tempfile
    with tempfile.TemporaryDirectory() as tmpdir:
        engine = AutoLabelEngine(os.path.join(tmpdir, "labels.jsonl"))
        # 非数字 progress
        result = engine.apply_event("issue.open", entity_id="ISSUE-1", extra={"progress": "abc"})
        assert "progress_" not in " ".join(result["labels"])
        # 无 progress extra
        result = engine.apply_event("issue.open", entity_id="ISSUE-1")
        assert "progress_" not in " ".join(result["labels"])
        # 合法 progress
        result = engine.apply_event("issue.open", entity_id="ISSUE-1", extra={"progress": 50})
        assert "progress_50%" in result["labels"]


if __name__ == "__main__":


    test_disposition_default()
    test_disposition_severity_map()
    test_disposition_trigger_map()
    test_parse_disposition()
    test_checker_good_code()
    test_checker_todo()
    test_checker_debug_print()
    test_auto_label_issue_open()
    test_auto_label_review_need_fix()
    test_auto_label_review_pass()
    test_disposition_overlap_signal()
    test_auto_label_progress_type_defense()
    print("✅ 评审机制测试全部通过")

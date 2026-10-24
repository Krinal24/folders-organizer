import os

from app.ai.batched import BatchedAnalyzer
from app.ai.prompts import build_batch_prompt, existing_folders


class ScriptedAnalyzer(BatchedAnalyzer):
    """Replies with canned text, split into awkward chunks like a real stream."""

    def __init__(self, replies, batch_size=40):
        super().__init__()
        self.batch_size = batch_size
        self.replies = list(replies)
        self.prompts = []

    def _stream_completion(self, system, user, max_tokens):
        self.prompts.append((system, user))
        reply = self.replies.pop(0)
        for start in range(0, len(reply), 7):
            yield reply[start:start + 7]


def doc(name, folder=""):
    return {
        "name": name,
        "relative_path": os.path.join(folder, name) if folder else name,
        "kind": "file",
        "extension": os.path.splitext(name)[1],
        "category": "documents",
        "size": 100,
    }


def image(name):
    return {**doc(name), "category": "images"}


def by_path(analyses):
    return {a.relative_path: a for a in analyses}


def test_parses_streamed_lines_into_moves():
    analyzer = ScriptedAnalyzer([
        "1|resumes|9|resume in name\n2|finance|8|invoice\n"
    ])

    result = by_path(analyzer.analyze_stream([doc("cv.pdf"), doc("invoice.pdf")]))

    assert result["cv.pdf"].action == "move"
    assert result["cv.pdf"].destination == "Documents/Resumes"
    assert result["cv.pdf"].confidence == 0.9
    assert result["invoice.pdf"].destination == "Documents/Finance"


def test_missing_items_are_retried_once_then_reviewed():
    analyzer = ScriptedAnalyzer([
        "Sure! Here you go:\n 1 | study | 7 | notes \n7|docs|5|out of range\n1|docs|5|duplicate id",
        "nonsense",
    ])

    result = by_path(analyzer.analyze_stream([doc("notes.pdf"), doc("other.pdf")]))

    assert result["notes.pdf"].destination == "Documents/Study"
    # The retry only asked about the missing file.
    assert analyzer.prompts[1][1] == "Items:\n1 | other.pdf"
    assert result["other.pdf"].action == "review"
    assert "usable answer" in result["other.pdf"].reason


def test_retry_recovers_missing_items():
    analyzer = ScriptedAnalyzer(["1|study|8|notes\n", "1|finance|9|invoice\n"])

    result = by_path(analyzer.analyze_stream([doc("notes.pdf"), doc("invoice.pdf")]))

    assert result["invoice.pdf"].destination == "Documents/Finance"


def test_drifted_format_still_uses_the_label():
    # Real output from gemma3:4b: it started echoing file names mid-reply.
    analyzer = ScriptedAnalyzer([
        "1 | docs | 7\n"
        "2 | personal | Degree_Certificate.pdf\n"
        "3 | study | Direct and Indirect Speech .pdf\n"
    ])
    files = [doc("x.pdf"), doc("Degree_Certificate.pdf"), doc("Direct and Indirect Speech .pdf")]

    result = by_path(analyzer.analyze_stream(files))

    assert result["x.pdf"].confidence == 0.7
    assert result["Degree_Certificate.pdf"].destination == "Documents/Personal"
    assert result["Degree_Certificate.pdf"].confidence == 0.6
    assert result["Direct and Indirect Speech .pdf"].destination == "Documents/Study"
    assert len(analyzer.prompts) == 1


def test_unknown_label_low_confidence_and_review_label():
    analyzer = ScriptedAnalyzer([
        "1|images|9|wrong\n2|work|2|guess\n3|review|5|no idea",
        "1|images|9|still wrong",
    ])

    result = by_path(analyzer.analyze_stream([doc("a.pdf"), doc("b.pdf"), doc("c.pdf")]))

    assert {a.action for a in result.values()} == {"review"}
    assert "usable answer" in result["a.pdf"].reason
    assert "maybe Documents/Work" in result["b.pdf"].reason


def test_already_in_destination_becomes_keep():
    analyzer = ScriptedAnalyzer(["1|study|8|notes"])
    file = doc("notes.pdf", folder=os.path.join("Documents", "Study", "Sem3"))

    [analysis] = analyzer.analyze_stream([file])

    assert analysis.action == "keep"
    assert analysis.destination is None


def test_groups_get_their_own_prompts_and_batches():
    analyzer = ScriptedAnalyzer(
        ["1|docs|5|x\n2|docs|5|x\n", "1|docs|5|x\n", "1|graphics|8|meme\n"],
        batch_size=2,
    )
    files = [doc("a.pdf"), image("pepe.png"), doc("b.pdf"), doc("c.pdf")]

    result = by_path(analyzer.analyze_stream(files))

    assert len(analyzer.prompts) == 3
    systems = [system for system, _ in analyzer.prompts]
    assert "sort documents" in systems[0] and "graphics" not in systems[0]
    assert "sort images" in systems[2] and "resumes" not in systems[2]
    assert result["pepe.png"].destination == "Images/Graphics"
    assert len(result) == 4


def test_existing_folders_become_labels():
    files = [doc("x.pdf", folder="College"), doc("y.pdf", folder="Documents"), doc("z.pdf")]

    assert existing_folders(files) == [("college", "College", "existing folder")]

    analyzer = ScriptedAnalyzer(["1|college|8|college file\n2|docs|5|x\n3|docs|5|x"])
    result = by_path(analyzer.analyze_stream(files))

    assert result[os.path.join("College", "x.pdf")].action == "keep"


def test_batch_prompt_is_compact():
    prompt = build_batch_prompt([doc("cv.pdf"), doc("n.pdf", folder="Old")])

    assert prompt == "Items:\n1 | cv.pdf\n2 | n.pdf | in Old"

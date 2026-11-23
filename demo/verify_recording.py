import re
from pathlib import Path

import av


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    recording = root / "demo" / "live-copilot-demo.mp4"
    with av.open(str(recording)) as video:
        duration = video.duration / av.time_base
        assert 180 <= duration <= 240, f"Recording is {duration:.1f}s"
        frame = next(video.decode(video=0))
        assert frame.width >= 1024 and frame.height >= 576
        assert video.streams.audio, "Expected the synthetic support audio track"

    for document in [root / "README.md", *sorted((root / "docs").glob("*.md"))]:
        for target in re.findall(r"\]\(([^) ]+)\)", document.read_text()):
            if "://" in target or target.startswith("#"):
                continue
            assert (document.parent / target.split("#", maxsplit=1)[0]).is_file(), (
                document.name,
                target,
            )
    print(
        f"Verified the {duration:.1f}s recording, audio track, and local documentation links."
    )


if __name__ == "__main__":
    main()

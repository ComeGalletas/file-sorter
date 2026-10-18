Placeholder text. Copy this file to `nsfw_level_v1.md` in this folder and replace everything with your own wording.

- The copy is git-ignored and never committed; this example is the only file here that is.
- The loader appends the text to the system prompt of `nsfw_level_v1`, after its body, separated by one blank line. It adds no heading, so write your own if you want one.
- The file must be at most 4096 bytes of UTF-8. A larger file, a symlink or anything that is not a regular file is refused.
- An empty file counts as absent. Set `PROMPTS_LOCAL=off` to ignore it.
- Files ending in `.example.md` are never loaded.

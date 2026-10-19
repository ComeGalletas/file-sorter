Placeholder text. Copy this file to `nsfw_level_v1.md` in this folder and replace everything with your own system text.

- The copy is git-ignored and never committed; this example is the only file here that is.
- The loader uses the text as the whole system prompt of `nsfw_level_v1`, in place of the committed body. The front matter (sampling options, schema, image size) and the user messages stay the committed ones.
- The committed prompt has no slots, so use none. A slot the committed prompt does not declare is refused.
- The file must be at most 16384 bytes of UTF-8. A larger file, a symlink or anything that is not a regular file is refused.
- An empty file counts as absent. Set `PROMPTS_LOCAL=off` to ignore it.
- Files ending in `.example.md` are never loaded.

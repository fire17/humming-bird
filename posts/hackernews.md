# Draft — not posted

Show HN: Humming Bird, a neon terminal garden with an async flock

I started with a terminal-art hummingbird and kept iterating until it became a tiny
game: mouse-planted nectar, pilot controls, a shared flock brain, and a scrolling world.
The renderer redraws at 30 Hz while sampling a 60-pose wing cycle at adjustable virtual
speed. Each companion has a separate worker process. Native Windows input and POSIX
release-event protocols are handled separately.

Source/downloads: https://github.com/fire17/humming-bird

I'd especially welcome feedback on glyph-channel compositing and keyboard portability.
This is cell art rather than pixel graphics, so fonts and terminal emulators matter.

Posting note: publish manually; add the X thread URL only after that thread exists.

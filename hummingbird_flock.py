"""Transport-free flock policy, shared by native processes and the web worker."""
from hummingbird_brain import visual_distance


def assign_targets(world, peers, reservations):
    live = {heart.ident: heart for heart in world.hearts}
    eligible = set(peers)
    if not world.player_mode:
        eligible.add(1)
    reservations = {bird: heart for bird, heart in reservations.items()
                    if bird in eligible and heart in live}
    reserved = set(reservations.values())
    positions = {}
    if 1 in eligible and 1 not in reservations:
        positions[1] = world._bird_center()
    for ident, peer in peers.items():
        if peer is not None and ident not in reservations:
            positions[ident] = (peer.x + (1 if world.compact else 15.5),
                                peer.y + (0 if world.compact else 5.5))
    candidates = []
    for ident, (x, y) in positions.items():
        for heart_id in set(live) - reserved:
            heart = live[heart_id]
            hx = heart.x + (0.5 if world.compact else 2.5)
            hy = heart.y + (0 if world.compact else 0.5)
            candidates.append((visual_distance(hx - x, hy - y), ident, heart_id))
    for _, ident, heart_id in sorted(candidates):
        if ident not in reservations and heart_id not in reserved:
            reservations[ident] = heart_id
            reserved.add(heart_id)
    world.assigned_target_id = reservations.get(1) if not world.player_mode else None
    return reservations


def step_brain(brain, message):
    return brain.step(
        now=float(message["now"]), dt=float(message["dt"]), width=int(message["width"]),
        compact=bool(message["compact"]), play_top=int(message["play_top"]),
        play_bottom=int(message["play_bottom"]), count=int(message["count"]),
        primary_leaf=int(message["primary_leaf"]), hearts=tuple(message["hearts"]),
        leaves=tuple(message["leaves"]), assigned_target=message.get("target_id"),
        neighbors=tuple(message["neighbors"]), calm=bool(message.get("calm", False)),
        extended_board=bool(message.get("extended_board", False)),
        view_origin=tuple(message.get("view_origin", (0, 0))),
    )

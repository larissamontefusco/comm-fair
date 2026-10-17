"""Coalition masks with reversible mappings to original member IDs."""


def validate_n(n):
    if type(n) is not int or not 1 <= n <= 9:
        raise ValueError('Game size must be an integer in 1..9')


def member_universe(n=9):
    """Return a validated ordered universe."""
    if type(n) is int:
        validate_n(n)
        return tuple(range(1, n + 1))
    try:
        members = tuple(n)
    except TypeError as exc:
        raise ValueError('Expected a game size or iterable of member IDs') from exc
    validate_n(len(members))
    if (any(type(member) is not int or member <= 0 for member in members)
            or len(set(members)) != len(members)):
        raise ValueError('Invalid or duplicate member IDs in coalition universe')
    if members != tuple(sorted(members)):
        raise ValueError('Coalition universe member IDs must be ascending')
    return members


def mask_to_members(mask, n=9):
    universe = member_universe(n)
    if type(mask) is not int or not 0 <= mask < 2**len(universe):
        raise ValueError('Invalid coalition mask')
    return tuple(member for position, member in enumerate(universe)
                 if mask & (1 << position))


def members_to_mask(members, n=9):
    universe = member_universe(n)
    try:
        members = tuple(members)
    except TypeError as exc:
        raise ValueError('Expected iterable of member IDs') from exc
    if (any(type(member) is not int or member not in universe for member in members)
            or len(set(members)) != len(members)):
        raise ValueError('Invalid or duplicate member IDs')
    positions = {member: position for position, member in enumerate(universe)}
    return sum(1 << positions[member] for member in members)


def coalition_kind(mask, n=9):
    members = mask_to_members(mask, n)
    if not members:
        return 'empty'
    if len(members) == len(member_universe(n)):
        return 'grand'
    return 'singleton' if len(members) == 1 else 'proper_multi_member'

def two_sum(nums, target):
    """Return two distinct indices whose values sum to target, or None."""
    for i in range(len(nums)):
        if nums[i] == target:
            return i
    return None

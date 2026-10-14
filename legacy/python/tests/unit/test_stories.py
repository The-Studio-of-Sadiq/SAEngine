"""Unit tests for the story system."""

from saengine.core.stories import Story, StorySystem


def test_default_story_system():
    stories = StorySystem.create_default(n_stories=3, typical_height=3.0, ground_height=4.0)
    # Base + 3 stories = 4 entries
    assert len(stories.stories) == 4
    assert stories.num_stories == 3

    assert stories.stories[0].name == "Base"
    assert stories.stories[0].elevation == 0.0

    assert stories.stories[1].name == "Story 1"
    assert stories.stories[1].height == 4.0
    assert stories.stories[1].elevation == 4.0

    assert stories.stories[2].name == "Story 2"
    assert stories.stories[2].height == 3.0
    assert stories.stories[2].elevation == 7.0

    assert stories.stories[3].name == "Roof"
    assert stories.stories[3].height == 3.0
    assert stories.stories[3].elevation == 10.0

    assert stories.total_height == 10.0


def test_add_remove_story():
    stories = StorySystem()
    stories.add_story("Base", height=0.0, is_base=True)
    s1 = stories.add_story("Level 1", height=3.5)
    s2 = stories.add_story("Level 2", height=3.0)

    assert stories.total_height == 6.5
    assert stories.elevations == [0.0, 3.5, 6.5]

    stories.remove_story(s1.id)
    # Remaining: Base, Level 2
    assert len(stories.stories) == 2
    assert stories.stories[1].elevation == 3.0


def test_story_serialization():
    stories = StorySystem.create_default(n_stories=2)
    d = stories.to_dict()

    restored = StorySystem.from_dict(d)
    assert len(restored.stories) == len(stories.stories)
    assert restored.elevations == stories.elevations

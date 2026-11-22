#!/usr/bin/env python3
#
# Generate a HTML export by serialising the static JSON files,
# and creating a structure for the HTML files.
#
# The server will need to handle routing or redirection, like from
# /t/name-of-topic/123 (original) --> /topics/123.html (archive)
#
import hashlib
import json
import math
import os
import shutil
from datetime import datetime
from pathlib import Path

from jinja2 import Environment, FileSystemLoader

REPO_ROOT = Path(__file__).resolve().parent.parent
JSON_DIR = REPO_ROOT / "json"
TEMPLATES_DIR = REPO_ROOT / "html" / "templates"
ASSETS_DIR = REPO_ROOT / "html" / "assets"
UPLOADS_DIR = REPO_ROOT / "uploads"
OUTPUT_DIR = REPO_ROOT / "dist"

# Discourse post_type value used for "small action" posts (e.g. "user closed this topic").
SMALL_ACTION_POST_TYPE = 3

ACTION_LABELS = {
    'closed.enabled': 'Closed',
    'closed.disabled': 'Opened',
    'autoclosed.enabled': 'Auto-closed',
    'autoclosed.disabled': 'Reopened',
    'archived.enabled': 'Archived',
    'archived.disabled': 'Unarchived',
    'pinned.enabled': 'Pinned',
    'pinned.disabled': 'Unpinned',
    'pinned_globally.enabled': 'Pinned globally',
    'pinned_globally.disabled': 'Unpinned globally',
    'banner.enabled': 'Pinned as banner',
    'banner.disabled': 'Unpinned as banner',
    'visible.enabled': 'Visible',
    'visible.disabled': 'Hidden',
    'split_topic': 'Split topic',
    'invited_user': 'Invited user',
    'invited_group': 'Invited group',
    'user_left': 'User left',
    'removed_user': 'Removed user',
    'removed_group': 'Removed group',
    'public_topic': 'Converted to public topic',
    'open_topic': 'Opened topic',
    'private_topic': 'Converted to private topic',
    'autobumped': 'Auto-bumped',
    'topic_created': 'Created topic',
}
ACTION_ICONS = {
    'closed.enabled': 'lock',
    'closed.disabled': 'lock-open',
    'autoclosed.enabled': 'lock',
    'autoclosed.disabled': 'lock-open',
    'archived.enabled': 'box-archive',
    'archived.disabled': 'folder-open',
    'pinned.enabled': 'thumbtack',
    'pinned.disabled': 'thumbtack',
    'pinned_globally.enabled': 'thumbtack',
    'pinned_globally.disabled': 'thumbtack',
    'banner.enabled': 'thumbtack',
    'banner.disabled': 'thumbtack',
    'visible.enabled': 'eye',
    'visible.disabled': 'eye-slash',
    'split_topic': 'right-from-bracket',
    'invited_user': 'user-plus',
    'invited_group': 'user-plus',
    'user_left': 'user-minus',
    'removed_user': 'user-minus',
    'removed_group': 'user-minus',
    'public_topic': 'comment',
    'open_topic': 'comment',
    'private_topic': 'envelope',
    'autobumped': 'hand-point-right',
    'topic_created': 'plus',
}

TRUST_LEVEL_LABELS = {0: "new", 1: "basic", 2: "member", 3: "regular", 4: "leader"}

TOP_PARTICIPANTS_PER_TOPIC = 5


# Discourse letter-avatar palette (lib/letter_avatar.rb); order matters.
AVATAR_COLORS = [
    "c67d28", "3d9bf3", "4af34b", "ee59a6", "34f0e0", "b19c9b", "f07891", "6f9a4e",
    "edb3f5", "ed655f", "59ef9b", "2bfe46", "a3d4f5", "41988e", "a587f6", "b5a626",
    "bbe5ce", "4da419", "b3f665", "ea5d25", "e19b73", "8e8cbc", "df788c", "f9ae1b",
    "f475e1", "898d66", "4bbf92", "bcef8e", "a4c791", "ad7895", "3bc359", "dec6dc",
    "4491bb", "ecccb3", "9fc348", "bc79bd", "a6a055", "b5e925", "ecb155", "7993a0",
    "eada6e", "f19dbf", "3ec8ea", "85f322", "58956e", "3be4f8", "b77776", "fbc32d",
    "71c47a", "c57346", "50afbb", "67e7ee", "f04885", "e495f1", "b4bc9f", "ac8455",
    "b487fb", "ecc23a", "d9b06d", "58f4c7", "ba9def", "71e660", "ce73a5", "f4b2a3",
    "e68b1a", "f17d59", "53a042", "6bbea6", "c5a1d2", "c6cbf5", "ee7513", "e47774",
    "839c29", "91b2a8", "8baadc", "e95f7d", "57b2e6", "9dc877", "ed8c4c", "e5b9ba",
    "90ced4", "ecd19e", "b9bd4f", "22d042", "54ee81", "858c86", "439d5e", "a8b319",
    "8c91f0", "97f17d", "43a26b", "c89c15", "a9adbd", "e274bd", "85e7bf", "c2a13f",
    "f14d63", "f1d935", "7bcc69", "d2c977", "e56c9b", "f05b48", "bb73d2", "f0a364",
    "b2d939", "b38774", "ccd318", "ba8739", "dfb087", "cc9497", "74df32", "5fc32e",
    "7ba0ec", "b5ac83", "8edcca", "f08c70", "ac91a4", "e47c2d", "8797f3", "2acd7d",
    "c0e974", "77aa72", "9e8a1a", "49beb7", "b9e5f3", "e36b37", "c4cdca", "848f3c",
    "e9c0ed", "3e96dc", "cdc98d", "6a8cbe", "a183cd", "87869e", "c68b51", "73ab20",
    "65b543", "958977", "258eb7", "b782af", "a87d85", "7c8e57", "ec9cab", "e8c25b",
    "dbc845", "90db22", "db5fbb", "919ad9", "a5b964", "7feea3", "e0b2c6", "779978",
    "7cd45c", "aca169", "e79b87", "9d8465", "7ab992", "35a633", "46a35a", "96bed5",
    "d26b3c", "a698b9", "9fc29f", "278dde", "cab0a1", "5f8ce5", "a88e57", "5daacb",
    "9f8e36", "0ea827", "5e9695", "bbce88", "9de0a6", "eb9ed0", "6de8d8", "8dc957",
    "d07c76", "8e7dd6", "13edae", "48db29", "ea666f", "a88e4f", "bc8723", "5f9b8f",
    "94ad74", "df705f", "e480ec", "ce7236", "c37758", "eb8c5e", "ebca7d", "e99b99",
    "d6d6ee", "f6c823", "977dab", "8491ac", "838e76", "c77e96", "3da27b", "3ab097",
    "d78d45", "e19adc", "dc4da7", "e9a140", "82dd89", "51bf81", "a9a28c", "aeb1de",
    "ecae2f", "e9bcb4", "45deac", "47e85d", "76d3ee", "9de053", "da6949", "7ea924",
]


def filter_avatar_color(username):
    # Mirrors Discourse's letter avatar choice: MD5 of the lowercased username, modulo the palette size.
    digest = hashlib.md5((username or "").lower().encode("utf-8")).hexdigest()
    return AVATAR_COLORS[int(digest[:15], 16) % len(AVATAR_COLORS)]


def filter_number_format(value):
    if value is None:
        return "0"
    return "{:,}".format(int(value))


def filter_short_date(value):
    if not value:
        return ""
    try:
        return datetime.fromisoformat(value).strftime("%d %b")
    except (TypeError, ValueError):
        return str(value)


def filter_compact_number(value):
    if value is None:
        return "0"
    number = float(value)
    for threshold, suffix in ((1_000_000_000, "b"), (1_000_000, "m"), (1_000, "k")):
        if abs(number) >= threshold:
            compact = number / threshold
            precision = 1 if abs(compact) < 10 else 0
            return f"{compact:.{precision}f}".rstrip("0").rstrip(".") + suffix
    return "{:,}".format(int(number))


def filter_read_time(word_count):
    if not word_count:
        return None
    return f"{max(1, math.ceil(word_count / 200))} min read"


def filter_seconds_to_time(seconds):
    if not seconds:
        return "0m"
    s = int(seconds)
    if s < 60:
        return f"{s}s"
    elif s < 3600:
        return f"{s // 60}m"
    elif s < 86400:
        return f"{s // 3600}h"
    else:
        return f"{s // 86400}d"


def filter_minutes_to_time(seconds):
    minutes = int(seconds or 0) // 60
    if minutes < 60:
        return f"{minutes}m"
    if minutes < 1440:
        return f"{minutes // 60}h"
    return f"{minutes // 1440}d"


def make_jinja_env():
    env = Environment(
        loader=FileSystemLoader(TEMPLATES_DIR),
        autoescape=True,
        trim_blocks=True,
        lstrip_blocks=True,
    )
    env.filters["number_format"] = filter_number_format
    env.filters["avatar_color"] = filter_avatar_color
    env.filters["short_date"] = filter_short_date
    env.filters["compact_number"] = filter_compact_number
    env.filters["read_time"] = filter_read_time
    env.filters["seconds_to_time"] = filter_seconds_to_time
    env.filters["minutes_to_time"] = filter_minutes_to_time
    return env


def load_json(name):
    path = JSON_DIR / name
    parts = [(int(part.stem.removeprefix(path.stem + ".")), part)
             for part in JSON_DIR.glob(f"{path.stem}.*.json")
             if part.stem.removeprefix(path.stem + ".").isdigit()]
    if not parts:
        with path.open(encoding="utf-8") as f:
            return json.load(f)
    parts.sort()
    if [number for number, _ in parts] != list(range(1, len(parts) + 1)):
        raise ValueError(f"Missing or duplicate numbered parts for {name}")
    data = []
    for _, part in parts:
        with part.open(encoding="utf-8") as f:
            data.extend(json.load(f))
    return data


def write_output(path, html):
    output_path = OUTPUT_DIR / path
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(html, encoding="utf-8")


def get_action_label(action_code):
    if not action_code:
        return "Action"
    return ACTION_LABELS.get(action_code, action_code.replace('.', ' ').replace('_', ' ').title())


def get_action_icon(action_code):
    return ACTION_ICONS.get(action_code, 'circle-info')


class Archive:
    """Loads the exported JSON files into memory and cross-links them for templating."""
    def __init__(self):
        self.categories = {c["id"]: c for c in load_json("categories.json")}
        self.users = {u["id"]: u for u in load_json("users.json")}
        self.users_by_username = {u["username_lower"]: u for u in self.users.values()}
        self.badges = {b["id"]: b for b in load_json("badges.json")}
        self.user_badges = load_json("user_badges.json")
        self.tags = {t["id"]: t for t in load_json("tags.json")}
        self.topics = {t["id"]: t for t in load_json("topics.json")}
        self.posts = {p["id"]: p for p in load_json("posts.json")}

        self.posts_by_topic = {}
        self.badges_by_user = {}

        self._link_posts()
        self._link_topics()
        self._link_user_badges()
        self._link_category_topics()

    def _link_posts(self):
        """Attach likers and small-action metadata; group posts by topic."""
        for post in self.posts.values():
            post["likes"] = [self.users[uid] for uid in post["like_user_ids"] if uid in self.users]

            post["is_action"] = post["post_type"] == SMALL_ACTION_POST_TYPE and bool(post.get("action_code"))
            if post["is_action"]:
                post["action_label"] = get_action_label(post["action_code"])
                post["action_icon"] = get_action_icon(post["action_code"])

            self.posts_by_topic.setdefault(post["topic_id"], []).append(post)

        for posts in self.posts_by_topic.values():
            posts.sort(key=lambda p: p["post_number"])

    def _link_topics(self):
        """Resolve tags and top participants for each topic."""
        for topic in self.topics.values():
            topic["tags"] = [self.tags[tid] for tid in topic["tag_ids"] if tid in self.tags]
            topic["has_solution"] = topic["solved_post_id"] is not None

            participants = [
                self.users[p["user_id"]] for p in topic["participants"] if p["user_id"] in self.users
            ]
            topic["participant_count"] = len(participants)
            topic["participants"] = participants[:TOP_PARTICIPANTS_PER_TOPIC]

    def _link_user_badges(self):
        badges_by_user_and_id = {}
        for grant in self.user_badges:
            badge = self.badges.get(grant["badge_id"])
            if not badge:
                continue

            user_id = grant["user_id"]
            user_badges = badges_by_user_and_id.setdefault(user_id, {})
            existing = user_badges.get(badge["id"])
            if existing:
                existing["user_grant_count"] += 1
                granted_at = grant.get("granted_at")
                if granted_at and (not existing["granted_at"] or granted_at > existing["granted_at"]):
                    existing["granted_at"] = granted_at
                continue

            merged = dict(badge)
            merged["granted_at"] = grant.get("granted_at")
            merged["user_grant_count"] = 1
            user_badges[badge["id"]] = merged
            self.badges_by_user.setdefault(user_id, []).append(merged)

    def _link_category_topics(self):
        for category in self.categories.values():
            category["topics"] = []
        for topic in self.topics.values():
            category = self.categories.get(topic["category_id"])
            if category:
                category["topics"].append(topic)

    def get_solved_post(self, topic):
        post_id = topic.get("solved_post_id")
        return self.posts.get(post_id) if post_id else None


def copy_static_assets():
    if OUTPUT_DIR.exists():
        shutil.rmtree(OUTPUT_DIR)
    shutil.copytree(ASSETS_DIR, OUTPUT_DIR)
    if UPLOADS_DIR.exists():
        shutil.copytree(UPLOADS_DIR, OUTPUT_DIR / "uploads")


def generate_index_page(env, archive):
    print("Generating: Index")
    html = env.get_template("index.html").render(categories=list(archive.categories.values()))
    write_output("index.html", html)


def generate_badges_page(env, archive):
    print("Generating: Badges")
    badges = list(archive.badges.values())

    badge_groups = {}
    for badge in badges:
        badge_groups.setdefault(badge.get("badge_grouping_name", "Other"), []).append(badge)

    sorted_groups = {}
    for group_name in sorted(badge_groups, key=lambda name: (badge_groups[name][0].get("grouping_position", 999), name)):
        sorted_groups[group_name] = sorted(badge_groups[group_name], key=lambda b: (b.get("badge_type_id", 0), b["name"]))

    total_grants = sum(badge.get("grant_count", 0) for badge in badges)

    html = env.get_template("badges.html").render(badges=badges, badge_groups=sorted_groups, total_grants=total_grants)
    write_output("badges.html", html)


def generate_badge_pages(env, archive):
    print("Generating: Badge pages")
    latest_grants = {}
    for grant in archive.user_badges:
        user = archive.users.get(grant["user_id"])
        if not user or grant["badge_id"] not in archive.badges:
            continue
        key = (grant["badge_id"], user["id"])
        existing = latest_grants.get(key)
        if not existing or (grant.get("granted_at") or "") > (existing["granted_at"] or ""):
            latest_grants[key] = {"user": user, "granted_at": grant.get("granted_at")}

    grants_by_badge = {}
    for (badge_id, _), entry in latest_grants.items():
        grants_by_badge.setdefault(badge_id, []).append(entry)

    for badge in archive.badges.values():
        grants = sorted(grants_by_badge.get(badge["id"], []), key=lambda g: g["granted_at"] or "", reverse=True)
        html = env.get_template("badge.html").render(badge=badge, grants=grants)
        write_output(os.path.join("badge", f"{badge['id']}.html"), html)


def generate_topics_index(env, archive):
    print("Generating: Topics index")
    topics = sorted(archive.topics.values(), key=lambda t: t.get("last_posted_at") or t.get("created_at"), reverse=True)
    html = env.get_template("topics.html").render(topics=topics, users=archive.users, category_title="All Topics")
    write_output("topics.html", html)


def generate_topic_pages(env, archive):
    print("Generating: Topic pages")
    for topic in archive.topics.values():
        posts = archive.posts_by_topic.get(topic["id"], [])
        solved_post = archive.get_solved_post(topic)
        html = env.get_template("topic.html").render(
            topic=topic,
            posts=posts,
            solved_post_id=topic["solved_post_id"],
            solved_post=solved_post,
            users=archive.users,
            categories=archive.categories,
            topic_participants=topic["participants"],
            topic_participant_count=topic["participant_count"],
        )
        write_output(os.path.join("t", f"{topic['id']}.html"), html)


def generate_user_pages(env, archive):
    """Generate single-page user profiles, computing each user's activity summary."""
    print("Generating: User profiles")
    all_posts = list(archive.posts.values())

    # (topic_id, post_number) -> author user_id, used to resolve "most replied to".
    post_number_lookup = {(p["topic_id"], p["post_number"]): p.get("user_id") for p in all_posts}

    # liker_id -> {author_id: count}, used to resolve "most liked".
    likes_given_lookup = {}
    for post in all_posts:
        author_id = post.get("user_id")
        for liker in post["likes"]:
            liker_id = liker["id"]
            if author_id and liker_id != author_id:
                counts = likes_given_lookup.setdefault(liker_id, {})
                counts[author_id] = counts.get(author_id, 0) + 1

    posts_by_user = {}
    for post in all_posts:
        posts_by_user.setdefault(post.get("user_id"), []).append(post)

    topics_by_user = {}
    for topic in archive.topics.values():
        topics_by_user.setdefault(topic.get("user_id"), []).append(topic)

    solved_post_ids = {t["solved_post_id"] for t in archive.topics.values() if t["solved_post_id"]}

    for user in archive.users.values():
        uid = user["id"]
        user_topics = topics_by_user.get(uid, [])
        user_posts = posts_by_user.get(uid, [])

        recent_topics = sorted(user_topics, key=lambda t: t.get("last_posted_at") or t.get("created_at"), reverse=True)
        top_topics = sorted(
            user_topics,
            key=lambda t: (t.get("views") or 0, t.get("like_count") or 0, t.get("posts_count") or 0),
            reverse=True,
        )[:5]

        replies = [p for p in user_posts if (p.get("post_number") or 0) > 1]
        recent_replies = sorted(replies, key=lambda p: p["created_at"], reverse=True)
        top_replies = sorted(replies, key=lambda p: (p.get("like_count") or 0, p["created_at"]), reverse=True)[:5]
        liked_posts = sorted(
            [p for p in user_posts if (p.get("like_count") or 0) > 0],
            key=lambda p: (p.get("like_count") or 0, p["created_at"]),
            reverse=True,
        )

        # most_liked_by: users who liked this user's posts most.
        liked_by_counts = {}
        for post in user_posts:
            for liker in post["likes"]:
                if liker["id"] != uid:
                    liked_by_counts[liker["id"]] = liked_by_counts.get(liker["id"], 0) + 1
        most_liked_by = sorted(
            [{"user": archive.users[lid], "count": cnt} for lid, cnt in liked_by_counts.items()],
            key=lambda x: -x["count"],
        )[:6]

        # most_liked: users whose posts this user liked most.
        most_liked = sorted(
            [{"user": archive.users[aid], "count": cnt} for aid, cnt in likes_given_lookup.get(uid, {}).items()],
            key=lambda x: -x["count"],
        )[:6]

        # most_replied_to: users this user replied to most.
        replied_to_counts = {}
        for post in user_posts:
            reply_number = post.get("reply_to_post_number")
            if reply_number:
                target_uid = post_number_lookup.get((post["topic_id"], reply_number))
                if target_uid and target_uid != uid:
                    replied_to_counts[target_uid] = replied_to_counts.get(target_uid, 0) + 1
        most_replied_to = sorted(
            [{"user": archive.users[tuid], "count": cnt} for tuid, cnt in replied_to_counts.items() if tuid in archive.users],
            key=lambda x: -x["count"],
        )[:6]

        # top_categories: categories ranked by total posts + topics.
        cat_post_counts = {}
        for post in user_posts:
            topic = archive.topics.get(post["topic_id"])
            if topic and topic.get("category_id"):
                cat_post_counts[topic["category_id"]] = cat_post_counts.get(topic["category_id"], 0) + 1
        cat_topic_counts = {}
        for topic in user_topics:
            if topic.get("category_id"):
                cat_topic_counts[topic["category_id"]] = cat_topic_counts.get(topic["category_id"], 0) + 1
        all_cat_ids = set(cat_post_counts) | set(cat_topic_counts)
        top_categories = sorted(
            [
                {"category": archive.categories[cid], "topics": cat_topic_counts.get(cid, 0), "replies": cat_post_counts.get(cid, 0)}
                for cid in all_cat_ids if cid in archive.categories
            ],
            key=lambda x: -(x["topics"] + x["replies"]),
        )[:5]

        solved_posts = sorted([post for post in user_posts if post["id"] in solved_post_ids], key=lambda p: p["created_at"], reverse=True)
        solutions_count = len(solved_posts)
        user_badges = archive.badges_by_user.get(uid, [])

        html = env.get_template("profile.html").render(
            user=user,
            solutions_count=solutions_count,
            trust_levels=TRUST_LEVEL_LABELS,
            recent_topics=recent_topics,
            recent_replies=recent_replies,
            liked_posts=liked_posts,
            solved_posts=solved_posts,
            top_topics=top_topics,
            top_replies=top_replies,
            most_liked_by=most_liked_by,
            most_liked=most_liked,
            most_replied_to=most_replied_to,
            top_categories=top_categories,
            user_badges=user_badges,
            topics=archive.topics,
        )
        write_output(os.path.join("u", f"{user['username_lower']}.html"), html)


def generate_users_directory_page(env, archive):
    print("Generating: Users directory")
    users = sorted(
        archive.users.values(),
        key=lambda u: (-(u.get("likes_received") or 0), -(u.get("post_count") or 0), (u.get("username") or "").lower()),
    )
    html = env.get_template("users.html").render(users=users)
    write_output("users.html", html)


def tag_sections(tags):
    """Group tags by tag group (alphabetical), ungrouped tags last."""
    by_group = {}
    for tag in tags:
        for name in tag.get("group_names") or ["Tags"]:
            by_group.setdefault(name, []).append(tag)
    names = sorted(by_group, key=lambda n: (n == "Tags", n.lower()))
    return [(n, sorted(by_group[n], key=lambda t: t["name"].lower())) for n in names]


def generate_tags_pages(env, archive):
    print("Generating: Tags")
    tags = list(archive.tags.values())

    html = env.get_template("tags.html").render(tag_sections=tag_sections(tags))
    write_output("tags.html", html)

    topics_by_tag_id = {}
    for topic in archive.topics.values():
        for tag in topic["tags"]:
            topics_by_tag_id.setdefault(tag["id"], []).append(topic)

    for tag in tags:
        topics_for_tag = sorted(
            topics_by_tag_id.get(tag["id"], []),
            key=lambda t: t.get("last_posted_at") or t.get("created_at"),
            reverse=True,
        )
        html = env.get_template("tag_view.html").render(tag=tag, topics=topics_for_tag, users=archive.users)
        write_output(os.path.join("tags", f"{tag['slug']}.html"), html)


def generate_category_pages(env, archive):
    print("Generating: Categories")
    for category in archive.categories.values():
        topics = sorted(category["topics"], key=lambda t: t.get("last_posted_at") or t.get("created_at"), reverse=True)
        subcategories = [c for c in archive.categories.values() if c.get("parent_category_id") == category["id"]]
        parent_category = archive.categories.get(category.get("parent_category_id"))
        html = env.get_template("category.html").render(category=category, parent_category=parent_category, topics=topics, users=archive.users, subcategories=subcategories)
        write_output(os.path.join("c", f"{category['id']}.html"), html)


def generate_static_page(env, filename):
    html = env.get_template(filename).render()
    write_output(filename, html)


def main():
    print("Copying: Assets/Uploads")
    copy_static_assets()

    env = make_jinja_env()
    archive = Archive()

    generate_index_page(env, archive)
    generate_badges_page(env, archive)
    generate_badge_pages(env, archive)
    generate_topics_index(env, archive)
    generate_topic_pages(env, archive)
    generate_user_pages(env, archive)
    generate_users_directory_page(env, archive)
    generate_tags_pages(env, archive)
    generate_category_pages(env, archive)
    generate_static_page(env, "404.html")

    print(" ✓ Generation complete.")


if __name__ == "__main__":
    main()

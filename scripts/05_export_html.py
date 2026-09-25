#!/usr/bin/env python3
#
# Generate a HTML export by serialising the static JSON files,
# and creating a structure for the HTML files.
#
# The server will need to handle routing or redirection, like from
# /t/name-of-topic/123 (original) --> /topics/123.html (archive)
#

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


# --- Jinja2 filters -------------------------
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


def make_jinja_env():
    env = Environment(
        loader=FileSystemLoader(TEMPLATES_DIR),
        autoescape=True,
        trim_blocks=True,
        lstrip_blocks=True,
    )
    env.filters["number_format"] = filter_number_format
    env.filters["short_date"] = filter_short_date
    env.filters["compact_number"] = filter_compact_number
    env.filters["read_time"] = filter_read_time
    env.filters["seconds_to_time"] = filter_seconds_to_time
    return env


def load_json(name):
    with open(JSON_DIR / name, encoding="utf-8") as f:
        return json.load(f)


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
        self.groups = {g["id"]: g for g in load_json("groups.json")}
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
        for grant in self.user_badges:
            badge = self.badges.get(grant["badge_id"])
            if not badge:
                continue
            merged = dict(badge)
            merged["granted_at"] = grant.get("granted_at")
            self.badges_by_user.setdefault(grant["user_id"], []).append(merged)

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

        recent_topics = sorted(user_topics, key=lambda t: t.get("last_posted_at") or t.get("created_at"), reverse=True)[:10]
        top_topics = sorted(
            user_topics,
            key=lambda t: (t.get("views") or 0, t.get("like_count") or 0, t.get("posts_count") or 0),
            reverse=True,
        )[:5]

        replies = [p for p in user_posts if (p.get("post_number") or 0) > 1]
        recent_replies = sorted(replies, key=lambda p: p["created_at"], reverse=True)[:10]
        top_replies = sorted(replies, key=lambda p: (p.get("like_count") or 0, p["created_at"]), reverse=True)[:5]
        liked_posts = sorted(
            [p for p in user_posts if (p.get("like_count") or 0) > 0],
            key=lambda p: (p.get("like_count") or 0, p["created_at"]),
            reverse=True,
        )[:10]

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

        solutions_count = sum(1 for post_id in solved_post_ids if archive.posts.get(post_id, {}).get("user_id") == uid)
        primary_group = archive.groups.get(user.get("primary_group_id"))
        user_badges = archive.badges_by_user.get(uid, [])

        html = env.get_template("profile.html").render(
            user=user,
            primary_group=primary_group,
            solutions_count=solutions_count,
            trust_levels=TRUST_LEVEL_LABELS,
            recent_topics=recent_topics,
            recent_replies=recent_replies,
            liked_posts=liked_posts,
            solved_posts=[],  # not currently tracked per-user
            top_topics=top_topics,
            top_replies=top_replies,
            most_liked_by=most_liked_by,
            most_liked=most_liked,
            most_replied_to=most_replied_to,
            top_categories=top_categories,
            user_badges=user_badges,
            topics=archive.topics,
        )
        write_output(os.path.join("u", f"{user['username']}.html"), html)


def generate_users_directory_page(env, archive):
    print("Generating: Users directory")
    users = sorted(
        archive.users.values(),
        key=lambda u: (-(u.get("likes_received") or 0), -(u.get("post_count") or 0), (u.get("username") or "").lower()),
    )
    html = env.get_template("users.html").render(users=users)
    write_output("users.html", html)


def generate_tags_pages(env, archive):
    print("Generating: Tags")
    tags = list(archive.tags.values())

    html = env.get_template("tags.html").render(tags=tags)
    write_output("tags.html", html)

    topics_by_tag_id = {}
    for topic in archive.topics.values():
        for tag in topic["tags"]:
            topics_by_tag_id.setdefault(tag["id"], []).append(topic)

    for tag in tags:
        topics_for_tag = topics_by_tag_id.get(tag["id"], [])
        html = env.get_template("tag_view.html").render(tag=tag, topics=topics_for_tag, users=archive.users)
        write_output(os.path.join("tags", f"{tag['slug']}.html"), html)


def generate_groups_pages(env, archive):
    print("Generating: Groups")
    groups = list(archive.groups.values())
    html = env.get_template("groups.html").render(groups=groups)
    write_output("groups.html", html)

    for group in groups:
        members = [archive.users[uid] for uid in group["member_user_ids"] if uid in archive.users]
        html = env.get_template("group.html").render(group=group, members=members)
        write_output(os.path.join("g", f"{group['id']}.html"), html)


def generate_category_pages(env, archive):
    print("Generating: Categories")
    for category in archive.categories.values():
        topics = sorted(category["topics"], key=lambda t: t.get("last_posted_at") or t.get("created_at"), reverse=True)
        subcategories = [c for c in archive.categories.values() if c.get("parent_category_id") == category["id"]]
        html = env.get_template("category.html").render(
            category=category, topics=topics, users=archive.users, subcategories=subcategories
        )
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
    generate_topics_index(env, archive)
    generate_topic_pages(env, archive)
    generate_user_pages(env, archive)
    generate_users_directory_page(env, archive)
    generate_tags_pages(env, archive)
    generate_groups_pages(env, archive)
    generate_category_pages(env, archive)
    generate_static_page(env, "404.html")

    print(" ✓ Generation complete.")


if __name__ == "__main__":
    main()

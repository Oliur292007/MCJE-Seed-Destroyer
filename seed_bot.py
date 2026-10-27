import json
import os
import random
import time
import urllib.parse
import urllib.request
import urllib.error
from pathlib import Path

API_URL = "https://www.mineseedfinder.com/scan/java"
HISTORY_FILE = Path("posted_seeds.txt")

WEBHOOK_URL = os.environ["DISCORD_WEBHOOK_URL"]
ROLE_ID = os.environ["MINECRAFT_ROLE_ID"]

STRUCTURES = {
    5: "🏘️ Village",
    11: "🌀 Ruined Portal",
    14: "💎 Buried Treasure",
    24: "⚔️ Trial Chambers",
    13: "🏚️ Ancient City",
    7: "🚢 Shipwreck",
}


def read_history():
    if not HISTORY_FILE.exists():
        return set()

    return {
        line.strip()
        for line in HISTORY_FILE.read_text().splitlines()
        if line.strip()
    }


def scan_seed(seed):
    params = urllib.parse.urlencode({
        "seed": seed,
        "x": 0,
        "z": 0,
        "radius": 100,
        "max": 40,
        "types": ",".join(map(str, STRUCTURES)),
    })

    request = urllib.request.Request(
        f"{API_URL}?{params}",
        headers={
            "User-Agent": "Minecraft-JE-Seed-Destroyer/1.0",
        },
    )

    with urllib.request.urlopen(request, timeout=45) as response:
        data = json.loads(
            response.read().decode("utf-8")
        )

    if data.get("error"):
        raise RuntimeError(data["error"])

    return data.get("results", [])


def post_to_discord(message):
    payload = json.dumps({
        "content": f"<@&{ROLE_ID}>\n{message}",
        "allowed_mentions": {
            "parse": [],
            "roles": [ROLE_ID],
        },
    }).encode("utf-8")

    request = urllib.request.Request(
        WEBHOOK_URL,
        data=payload,
        headers={
            "Content-Type": "application/json",
            "User-Agent": "Minecraft-JE-Seed-Destroyer/1.0",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(
            request,
            timeout=30
        ) as response:

            if response.status not in (200, 204):
                raise RuntimeError(
                    f"Discord returned HTTP {response.status}"
                )

    except urllib.error.HTTPError as exc:
        detail = exc.read().decode(
            "utf-8",
            errors="replace"
        )

        print(
            f"Discord HTTP {exc.code}: "
            f"{detail[:300]}"
        )

        raise RuntimeError(
            f"Discord posting failed: HTTP {exc.code}"
        ) from None


def structure_name(item):
    return (
        item.get("name", "")
        .lower()
        .replace(" ", "_")
    )


def get_structure_label(name):
    for label in STRUCTURES.values():
        clean_name = (
            label.split(" ", 1)[1]
            .lower()
            .replace(" ", "_")
        )

        if clean_name == name:
            return label

    return f"📌 {name.replace('_', ' ').title()}"


def main():
    history = read_history()
    best = None

    # Java Edition uses 64-bit signed seeds.
    min_seed = -(2**63)
    max_seed = 2**63 - 1

    # Try multiple unique candidates.
    for _ in range(30):

        seed = random.randint(
            min_seed,
            max_seed
        )

        seed_string = str(seed)

        if seed_string in history:
            continue

        try:
            results = scan_seed(seed)

        except Exception as exc:
            print(
                f"Scan failed for candidate: {exc}"
            )

            time.sleep(2)
            continue

        if not results:
            continue

        found_types = {
            structure_name(item)
            for item in results
            if structure_name(item)
        }

        score = len(found_types)

        # Give extra priority to useful structures.
        if "village" in found_types:
            score += 2

        if "ruined_portal" in found_types:
            score += 2

        if "buried_treasure" in found_types:
            score += 1

        if "ancient_city" in found_types:
            score += 1

        if "trial_chambers" in found_types:
            score += 1

        candidate = (
            score,
            seed,
            results
        )

        if best is None or score > best[0]:
            best = candidate

        # Excellent candidate.
        if score >= 6:
            break

        time.sleep(1)

    if best is None:
        raise RuntimeError(
            "No usable unposted Java seed found. "
            "Will retry at the next schedule."
        )

    _, seed, results = best

    lines = [
        "💀 **MINECRAFT JE — SEED DESTROYER..!**",
        "",
        f"🎲 **Java Seed:** `{seed}`",
        "☕ **Edition:** Minecraft Java Edition",
        "📍 **Search area:** Structures near spawn",
        "",
        "**🔥 Nearby structure predictions:**",
    ]

    for item in results[:20]:

        name = structure_name(item)

        label = get_structure_label(name)

        if "x" in item and "z" in item:

            lines.append(
                f"• {label} — "
                f"X: `{item['x']}`, "
                f"Z: `{item['z']}`"
            )

        else:
            lines.append(
                f"• {label}"
            )

    lines += [
        "",
        "🗺️ [Open Java Seed Map]"
        "(https://mcseedmap.net/)",
        "",
        "ℹ️ Structure locations are "
        "API-generated predictions and "
        "have not been independently verified.",
        "",
        "━━━━━━━━━━━━━━━━━━━━",
        "💀 *Automatically selected by "
        "Minecraft JE Seed Destroyer*",
    ]

    # Post first.
    # Save history only after Discord succeeds.
    post_to_discord(
        "\n".join(lines)
    )

    history.add(seed_string)

    HISTORY_FILE.write_text(
        "\n".join(sorted(history)) + "\n"
    )

    print(
        f"Posted new Java seed "
        f"{seed} successfully."
    )


if __name__ == "__main__":
    main()

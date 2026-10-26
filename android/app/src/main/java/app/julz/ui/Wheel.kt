package app.julz.ui

import app.julz.feed.Kind

/** The wheel picker's logic (251): one word in the middle is the pick, its neighbours half
 *  hidden at the sides. One component for every pick of one among several (D1): Messages'
 *  filters, the Todos views, the chat modes. Only picks a view or a mode, never writes. */
object Wheel {
    /** The item whose centre is nearest [mid], from (index, centre) pairs in the same pixels */
    fun nearest(centres: List<Pair<Int, Float>>, mid: Float): Int? =
        centres.minByOrNull { kotlin.math.abs(it.second - mid) }?.first

    /** Copies of the words in a loop, for the chat's one word wheel, stepped round by a swipe. A
     *  wheel of words in a row is a fixed row with ends, as iOS's picker is for what is not cyclic
     *  (my note 26 Oct): a loop of copies stood the same word on both sides. One word does not loop */
    const val LOOP = 1000
    fun slots(count: Int, vertical: Boolean) = if (vertical && count > 1) count * LOOP else count

    /** A pull past an end: the strip follows [delta] less the further it is out, never past [limit],
     *  as a rubber band does; a little over half the finger at first */
    fun rubber(pull: Float, delta: Float, limit: Float): Float {
        val give = (1f - kotlin.math.abs(pull) / limit).coerceIn(0f, 1f)
        return (pull + delta * 0.55f * give * give).coerceIn(-limit * 0.999f, limit * 0.999f)
    }

    /** Whether a new word in the middle ticks: [last] is the word that ticked or was placed last.
     *  Not while the wheel places itself as it comes on screen ([placing]), and not for the placed
     *  word seen a frame later: that ticked once on every arrival at Messages or Chat (my note 26 Oct) */
    fun tick(last: Int?, middle: Int?, placing: Boolean) = !placing && middle != null && last != null && middle != last

    /** The word at slot [slot] */
    fun real(slot: Int, count: Int) = slot % count

    /** The slot holding word [target] nearest to slot [from], so a pick rolls the short way round */
    fun closest(from: Int, target: Int, count: Int): Int {
        val ahead = Math.floorMod(target - from, count)
        return if (ahead <= count / 2) from + ahead else from + ahead - count
    }

    /** One swipe, one step, round the loop (the chat's wheel shows one word): up or left goes to
     *  the next, as TabSwipe does, and a swipe shorter than [threshold] stays */
    fun step(selected: Int, count: Int, d: Float, threshold: Float): Int = when {
        d <= -threshold -> (selected + 1) % count
        d >= threshold -> (selected - 1 + count) % count
        else -> selected
    }

    /** Where the light's two edges sit between two words, 0 on the first, 1 on the next, from [t],
     *  how far the middle has gone from one to the other: (the edge behind, the edge on the way).
     *  It rides the word for the first 20 percent, then the edge on the way runs ahead and the one
     *  behind catches up, so the light stretches across the gap and gathers on the next word, as
     *  an elastic tab indicator does (my note 26 Oct: the frame looked stale). Going back is the
     *  mirror, so the edge on the way always leads. Pure, so no clock and no jump */
    fun edges(t: Float): Pair<Float, Float> {
        fun s(x: Float) = x.coerceIn(0f, 1f).let { it * it * (3 - 2 * it) }
        return s((t - 0.35f) / 0.45f) to s((t - 0.2f) / 0.45f)
    }

    /** How much of the elastic edges (Wheel.edges) to use at [speed], in words a second: all of
     *  it on a slow move, none on a fast flick, where it crossed a word every frame and strobed
     *  between stretched and gathered (found on video, my note 26 Oct) */
    fun calm(speed: Float) = (1f - (kotlin.math.abs(speed) - 2f) / 4f).coerceIn(0f, 1f)

    /** How far the light streaks along the motion at [speed], as a share of its width: squash and
     *  stretch, more the faster the strip goes, never more than half */
    fun streak(speed: Float) = (kotlin.math.abs(speed) / 8f).coerceAtMost(1f) * 0.5f

    /** The light's height while stretched, as a share of its own: thinner as it stretches, so it
     *  keeps its volume (squash and stretch), never by more than a few percent */
    fun squash(edges: Pair<Float, Float>) = squash(edges.second - edges.first)

    /** The same for any [stretch], the extra width as a share of the light's own: a pull past an
     *  end stretches it too */
    fun squash(stretch: Float) = 1f - 0.15f * stretch.coerceIn(0f, 1f)

    /** How big a word draws, from [d], its distance from the middle in words: the middle one a
     *  little bigger, as a drum's middle row, falling off smoothly to its own size a word away (my
     *  idea 26 Oct). Only the middle grows: the neighbours keep 14 sp, the design's smallest */
    const val MAG = 1.1f
    fun magnify(d: Float): Float {
        val x = kotlin.math.abs(d).coerceIn(0f, 1f)
        return 1f + (MAG - 1f) * (1f - x * x * (3 - 2 * x))
    }

    /** How far apart the ticks past an end stand while it is pulled, as a share of their gap at rest:
     *  they spread as a stretched spring and close again (my note 26 Oct: they lacked life) */
    fun spread(pull: Float, limit: Float) = 1f + 1.5f * (kotlin.math.abs(pull) / limit).coerceIn(0f, 1f)

    /** A pick landing: the light swells this much and springs back, with the haptic tick, so the
     *  choice reads as made (Liquid Glass's press); a little bounce, settled in about 300 ms */
    const val POP = 1.06f
    val pop = androidx.compose.animation.core.spring<Float>(dampingRatio = 0.5f,
        stiffness = androidx.compose.animation.core.Spring.StiffnessMedium)

    /** How a fling lands: done within a pixel of the word, as Compose's Int and Offset springs are; the
     *  last frame puts it on the word. At the Float default, 0.01 px, it crept on unseen for about
     *  250 ms, and the pick, so Messages' list, waited for it (my note 26 Oct) */
    /** The speed a landing starts with, toward a word [delta] pixels away: the finger's [velocity],
     *  no faster than the settle spring can stop in that distance. A critically damped spring
     *  passes its target only when it starts faster than its stiffness's root times the distance;
     *  the word is often nearer than the flick would carry (in view, or the end), and the strip swung
     *  up to 250 px past and back (found on video, 26 Oct). A flick the other way keeps its speed */
    fun landingSpeed(velocity: Float, delta: Float): Float {
        if (velocity * delta <= 0f) return velocity
        val most = kotlin.math.sqrt(androidx.compose.animation.core.Spring.StiffnessMediumLow) * kotlin.math.abs(delta)
        return velocity.coerceIn(-most, most)
    }

    val settle = androidx.compose.animation.core.spring(
        stiffness = androidx.compose.animation.core.Spring.StiffnessMediumLow, visibilityThreshold = 1f)

    /** The word a fling lands on: [travel] is how far a free decay would carry the middle, less how
     *  far the nearest word already sits off it, in pixels; [size] a word's width with its gap. A
     *  flick faster than [minVelocity] moves at least one word, so no precise swipe is needed. It
     *  never goes further than the other [count] - 1 words: with two, a hard fling came back round
     *  to the same word and looked like nothing (my test 26 Oct) */
    fun landing(nearest: Int, travel: Float, size: Float, velocity: Float, minVelocity: Float, count: Int = Int.MAX_VALUE): Int {
        val steps = Math.round(travel / size).coerceIn(-(count - 1), count - 1)
        return nearest + if (steps == 0 && kotlin.math.abs(velocity) >= minVelocity) (if (velocity > 0) 1 else -1) else steps
    }

    /** What TalkBack says for a word: its place, since the row hides most of itself */
    fun say(word: String, index: Int, count: Int) = "$word, ${index + 1} of $count"

    /** Messages: All (null), then the kinds that have notices; the chosen one stays even when
     *  empty, so a notification's filter never vanishes from under me (22d) */
    fun kinds(present: Set<Kind>, chosen: Kind?): List<Kind?> =
        listOf<Kind?>(null) + Kind.entries.filter { it in present || it == chosen }

    // Todos: a list's name comes from a file, which cannot hold a slash, so these never clash
    const val BOARD = "/board"
    const val ALL = "/all"

    /** Todos: the board, all lists, then each list on its own; All lists is the default. One list
     *  gets no view of its own: it would show the same card as All lists */
    fun todoViews(lists: List<String>) = listOf(BOARD, ALL) + if (lists.size > 1) lists else emptyList()

    /** Where [view] sits; a list that is gone falls back to All lists */
    fun todoIndex(view: String, lists: List<String>) = todoViews(lists).indexOf(view).takeIf { it >= 0 } ?: 1

    /** The chat modes (135, 133b): the key julz-chat gets, and the word shown. At most one on */
    val MODES = listOf("" to "Chat", "learn" to "Learn", "notes" to "Notes")
}

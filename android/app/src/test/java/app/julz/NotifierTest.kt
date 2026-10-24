package app.julz

import android.app.NotificationManager
import app.julz.feed.Kind
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/** Which kinds pop up. Android lets an app set a channel's importance only when it creates it,
 *  so raising one means a new channel id and deleting the old one. */
class NotifierTest {
    @Test fun runsPopUpLikeApprovalsAndWarnings() {
        for (k in listOf(Kind.APPROVAL, Kind.WARNING, Kind.RUN))
            assertEquals(k.name, NotificationManager.IMPORTANCE_HIGH, Notifier.importance(k))
        assertEquals(NotificationManager.IMPORTANCE_MIN, Notifier.importance(Kind.CHANGE))
        for (k in listOf(Kind.INBOX, Kind.TODO, Kind.REVIEW))
            assertEquals(k.name, NotificationManager.IMPORTANCE_LOW, Notifier.importance(k))
    }

    @Test fun runsGetANewChannelAndTheOldOneGoes() {
        assertEquals("kind_run_2", Notifier.channelId(Kind.RUN))
        assertTrue("kind_run" in Notifier.RETIRED)
        // the other channels keep their ids, so my own settings on them stay
        for (k in Kind.entries.filter { it != Kind.RUN })
            assertEquals("kind_" + k.name.lowercase(), Notifier.channelId(k))
        assertTrue(Kind.entries.none { Notifier.channelId(it) in Notifier.RETIRED })
    }

    /** A tap opens the notice's place (13d). The extra is read from an intent any app can send,
     *  so only an exact kind name counts (SECURITY.md threat 133). */
    @Test fun aTapOpensTheKindsScreen() {
        assertEquals(Notifier.Target.APPROVE, Notifier.target(Kind.APPROVAL.name))
        assertEquals(Notifier.Target.TODOS, Notifier.target(Kind.TODO.name))
        assertEquals(Notifier.Target.INBOX, Notifier.target(Kind.INBOX.name))
        for (k in listOf(Kind.RUN, Kind.REVIEW, Kind.CHANGE, Kind.WARNING))
            assertEquals(k.name, Notifier.Target.MESSAGES, Notifier.target(k.name))
    }

    @Test fun anythingButAKindNameOpensNothing() {
        for (s in listOf(null, "", "approval", "k_approval", " APPROVAL", "APPROVAL\n", "APPROVE", "https://x"))
            assertNull(s.toString(), Notifier.target(s))
    }

    /** A tap on a warning, run, review or change opens Messages filtered to that kind, not All
     *  (asked 18 Oct); the same exact kind name, nothing else picks a filter (133). */
    @Test fun aTapForMessagesFiltersToItsKind() {
        for (k in listOf(Kind.RUN, Kind.REVIEW, Kind.CHANGE, Kind.WARNING)) assertEquals(k, Notifier.filter(k.name))
        for (k in listOf(Kind.APPROVAL, Kind.TODO, Kind.INBOX)) assertNull(k.name, Notifier.filter(k.name))
        for (s in listOf(null, "", "warning", "k_warning", " WARNING", "WARNING\n", "https://x")) assertNull(s.toString(), Notifier.filter(s))
    }

    @Test fun eachKindHasItsOwnPendingIntent() {
        // Android ignores extras when it matches PendingIntents: a shared request code would
        // give every notification the last kind's extra
        val codes = Kind.entries.map { Notifier.requestCode(it) }
        assertEquals(codes.size, codes.toSet().size)
        assertTrue(codes.none { it == 0 })
    }

    /** No tray entry or sound for what the open screen already shows (asked 18 Oct). */
    @Test fun theOpenScreenQuietsWhatItShows() {
        assertEquals(setOf(Kind.APPROVAL, Kind.RUN), Notifier.quietOn(Notifier.Target.APPROVE))
        assertEquals(setOf(Kind.TODO), Notifier.quietOn(Notifier.Target.TODOS))
        assertEquals(setOf(Kind.INBOX), Notifier.quietOn(Notifier.Target.INBOX))
        assertEquals(Kind.entries.toSet(), Notifier.quietOn(Notifier.Target.MESSAGES))
        // the app in the background or another screen: everything notifies
        assertEquals(emptySet<Kind>(), Notifier.quietOn(null))
    }

    @Test fun aWarningStillRingsOnApprove() {
        val counts = mapOf(Kind.APPROVAL to 1, Kind.RUN to 2, Kind.WARNING to 1)
        assertEquals(mapOf(Kind.WARNING to 1), Notifier.loud(counts, Notifier.Target.APPROVE))
        assertEquals(counts, Notifier.loud(counts, null))
    }
}

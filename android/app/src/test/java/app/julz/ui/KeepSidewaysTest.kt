package app.julz.ui

import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.input.nestedscroll.NestedScrollSource
import androidx.compose.ui.unit.Velocity
import kotlinx.coroutines.runBlocking
import org.junit.Assert.assertEquals
import org.junit.Test

class KeepSidewaysTest {
    @Test fun aDragOnAScrollingRowNeverReachesThePager() {
        // what the row could not scroll stays with the row: the pager gets no sideways rest
        assertEquals(Offset(-300f, 0f),
            KeepSideways.onPostScroll(Offset(-80f, 0f), Offset(-300f, 40f), NestedScrollSource.UserInput))
        assertEquals(Velocity(900f, 0f), runBlocking { KeepSideways.onPostFling(Velocity.Zero, Velocity(900f, 50f)) })
    }

    @Test fun upAndDownStillGoToThePage() {
        assertEquals(Offset.Zero, KeepSideways.onPostScroll(Offset.Zero, Offset(0f, 120f), NestedScrollSource.UserInput))
    }
}

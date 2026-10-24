package app.julz.ui

import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class ArrivedTest {
    @Test fun aCardAssemblesOnlyTheFirstTimeItArrives() {
        // swiping back to Now built its cards again and they assembled again, mid swipe (18 Oct)
        assertTrue(Arrived.first("test-now-week"))
        assertFalse(Arrived.first("test-now-week"))
        assertTrue(Arrived.first("test-spec-abc"))
    }
}

package app.julz.ui

import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Rect
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

/** A tap outside the field ends editing and still acts (228): the rule Shell applies. */
class TapOutTest {
    private val field = Rect(40f, 100f, 300f, 156f)
    private val add = Rect(310f, 100f, 360f, 156f)
    private val keeps = listOf(field, add)

    @Test fun aTapOutsideEndsEditing() {
        assertTrue(TapOut.endsEditing(Offset(200f, 600f), Offset(202f, 601f), 8f, keeps))  // a goal row, a tab, empty space
        assertTrue(TapOut.endsEditing(Offset(200f, 600f), Offset(200f, 600f), 8f, emptyList()))
    }

    @Test fun theFieldAndItsAddKeepIt() {
        assertFalse(TapOut.endsEditing(Offset(100f, 120f), Offset(100f, 120f), 8f, keeps))
        assertFalse(TapOut.endsEditing(Offset(330f, 130f), Offset(331f, 130f), 8f, keeps))
    }

    @Test fun aScrollIsNoTap() {
        assertFalse(TapOut.endsEditing(Offset(200f, 600f), Offset(200f, 500f), 8f, keeps))
        assertTrue(TapOut.endsEditing(Offset(200f, 600f), Offset(205f, 606f), 8f, keeps))  // within the slop
    }

    @Test fun whereTheFingerLiftsCounts() {
        // Down outside, up inside the field (within the slop): the field took it
        assertFalse(TapOut.endsEditing(Offset(42f, 97f), Offset(42f, 101f), 8f, keeps))
    }
}

package app.julz.ui

import org.junit.Assert.assertEquals
import org.junit.Test

class RowSizeTest {
    @Test fun aRowThatFitsKeepsItsSize() {
        assertEquals(14f, rowSize(listOf(80, 120, 100), avail = 130f, base = 14f, least = 7f), 0.001f)
    }

    @Test fun theWidestLabelSetsTheSizeForTheWholeRow() {
        // Messages is 200 px wide in a 150 px slot: every label in the row gets 3/4 of the size
        assertEquals(10.5f, rowSize(listOf(60, 200, 110), avail = 150f, base = 14f, least = 7f), 0.001f)
    }

    @Test fun neverUnderTheLeastSize() {
        assertEquals(7f, rowSize(listOf(1000), avail = 100f, base = 14f, least = 7f), 0.001f)
    }

    @Test fun noLabelsOrNoWidthKeepsTheBase() {
        assertEquals(14f, rowSize(emptyList(), avail = 100f, base = 14f, least = 7f), 0.001f)
        assertEquals(14f, rowSize(listOf(0), avail = 100f, base = 14f, least = 7f), 0.001f)
    }
}

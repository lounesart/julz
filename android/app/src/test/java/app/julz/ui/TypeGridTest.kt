package app.julz.ui

import org.junit.Assert.assertEquals
import org.junit.Test

class TypeGridTest {
    /** Every text style on a 4 dp grid (22d): lines keep one rhythm across screens */
    @Test fun everyLineHeightIsAMultipleOfFour() {
        val styles = mapOf("hero" to J.hero, "tl" to J.tl, "tm" to J.tm, "ts" to J.ts, "bodyText" to J.bodyText,
            "sec" to J.sec, "cap" to J.cap, "monoCap" to J.monoCap, "item" to J.item, "itemUnread" to J.itemUnread,
            "tag" to J.tag, "time" to J.time)
        for ((name, s) in styles) assertEquals(name, 0f, s.lineHeight.value % 4f)
    }

    @Test fun oneItemTitleHeavierOnlyWhenUnread() {
        assertEquals(J.item.fontSize, J.itemUnread.fontSize)
        assertEquals(true, J.itemUnread.fontWeight!!.weight > J.item.fontWeight!!.weight)
    }
}

package app.julz.ui

import org.junit.Assert.assertEquals
import org.junit.Test

/** History titles without the noise: no "Julz: " in front, the short id on its own. */
class WordsTest {
    @Test fun aTitleLosesItsPrefixAndKeepsItsId() {
        assertEquals("Note deleted" to "8954db42", Words.shortTitle("Julz: note deleted 8954db42"))
        assertEquals("Run done" to "ac7ec2c4", Words.shortTitle("Julz: run done ac7ec2c4"))
    }

    @Test fun aTitleWithoutAnIdStaysWhole() {
        assertEquals("1 open todo" to null, Words.shortTitle("Julz: 1 open todo"))
        assertEquals("No prefix here" to null, Words.shortTitle("No prefix here"))
        assertEquals("Julz:" to null, Words.shortTitle("Julz:"))  // nothing left: keep what came
    }
}

package app.julz.ui

import java.io.File
import org.junit.Assert.assertFalse
import org.junit.Test

class OutlineTest {
    /** Compose's border() draws a cut corner shape (Industrial) through a bitmap the size of the
     *  element: a 3060 line code block asked for 210 MB and the app died (25 Oct). Markdown blocks
     *  grow with the answer, so their borders are strokes, Modifier.outline */
    @Test fun markdownBordersAreStrokes() {
        val md = File("src/main/java/app/julz/ui/MarkdownView.kt").readText()
        assertFalse(".border( in MarkdownView.kt", ".border(" in md)
    }
}

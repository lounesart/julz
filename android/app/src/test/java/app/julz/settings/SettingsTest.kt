package app.julz.settings

import java.util.Base64
import javax.crypto.Cipher
import javax.crypto.KeyGenerator
import javax.crypto.spec.GCMParameterSpec
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/** SECURITY.md threats 88 and 94: only the julz server, only a token of the right shape, and
 *  the token never stored readable. A plain JVM AES key stands in for the Android Keystore. */
class SettingsTest {
    private val token = "tk_" + "p".repeat(29)

    private class JvmSealer : Sealer {
        private val key = KeyGenerator.getInstance("AES").apply { init(256) }.generateKey()
        override fun seal(plain: ByteArray): ByteArray {
            val c = Cipher.getInstance("AES/GCM/NoPadding").apply { init(Cipher.ENCRYPT_MODE, key) }
            return c.iv + c.doFinal(plain)
        }
        override fun open(sealed: ByteArray): ByteArray {
            val c = Cipher.getInstance("AES/GCM/NoPadding")
            c.init(Cipher.DECRYPT_MODE, key, GCMParameterSpec(128, sealed, 0, 12))
            return c.doFinal(sealed, 12, sealed.size - 12)
        }
    }

    @Test fun onlyTheJulzServerOnItsPort() {
        assertTrue(Settings.validServer("https://laptop.tail1234.ts.net:8444"))
        for (bad in listOf(
            "http://laptop.tail1234.ts.net:8444",  // plain http would send the token in clear
            "https://laptop.tail1234.ts.net",  // the default port is Open WebUI
            "https://laptop.tail1234.ts.net:8443",  // the approver
            "https://evil.example:8444",
            "https://laptop.tail1234.ts.net.evil.example:8444",
            "https://user@laptop.tail1234.ts.net:8444",
            "https://laptop.tail1234.ts.net:8444/x",
            "https://laptop.tail1234.ts.net:8444?x=1",
            "https://LAPTOP.tail1234.ts.net:8444 ",
            "https://a.b.tail1234.ts.net:8444",  // MagicDNS is machine.tailnet.ts.net
        )) assertFalse(bad, Settings.validServer(bad))
    }

    @Test fun onlyAPhoneTokenShape() {
        assertTrue(Settings.validToken(token))
        for (bad in listOf("", "tk_short", "tk_" + "P".repeat(29), token + "x", " $token"))
            assertFalse(bad, Settings.validToken(bad))
    }

    @Test fun tokenIsStoredSealedAndComesBack() {
        val store = HashMap<String, String>()
        val vault = TokenVault(JvmSealer(), store)
        vault.save(token)
        assertEquals(token, vault.load())
        assertFalse(store.values.any { token in it })  // never readable in storage
        val raw = Base64.getDecoder().decode(store.getValue(TokenVault.KEY))
        assertFalse(String(raw, Charsets.ISO_8859_1).contains(token))
    }

    @Test fun aTamperedTokenDoesNotOpen() {
        val store = HashMap<String, String>()
        val vault = TokenVault(JvmSealer(), store)
        vault.save(token)
        val raw = Base64.getDecoder().decode(store.getValue(TokenVault.KEY))
        raw[raw.size - 1] = (raw[raw.size - 1].toInt() xor 1).toByte()
        store[TokenVault.KEY] = Base64.getEncoder().encodeToString(raw)
        assertNull(vault.load())
    }

    @Test fun anotherKeyCannotOpenIt() {
        val store = HashMap<String, String>()
        TokenVault(JvmSealer(), store).save(token)
        assertNull(TokenVault(JvmSealer(), store).load())
    }

    @Test fun aBadTokenIsNeverSaved() {
        val store = HashMap<String, String>()
        val vault = TokenVault(JvmSealer(), store)
        assertFalse(vault.save("tk_short"))
        assertTrue(store.isEmpty())
    }

    @Test fun aSealedBadTokenIsNotAccepted() {
        // even a value that decrypts fine must still look like a phone token
        val sealer = JvmSealer()
        val store = HashMap<String, String>()
        store[TokenVault.KEY] = Base64.getEncoder().encodeToString(sealer.seal("tk_short".toByteArray()))
        assertNull(TokenVault(sealer, store).load())
    }

    @Test fun wipeForgetsIt() {
        val store = HashMap<String, String>()
        val vault = TokenVault(JvmSealer(), store)
        vault.save(token)
        vault.wipe()
        assertNull(vault.load())
        assertTrue(store.isEmpty())
    }
}

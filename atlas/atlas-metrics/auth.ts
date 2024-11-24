import NextAuth from "next-auth"
import "next-auth/jwt"

export const { handlers, auth, signIn, signOut } = NextAuth({
    debug: !!process.env.AUTH_DEBUG,
    providers: [],
    basePath: "/api/auth",
    session: { strategy: "jwt" },
    callbacks: {
        authorized({ request, auth }) {
            const { pathname } = request.nextUrl
            if (pathname === "/middleware-example") return !!auth
            return true
        },
        jwt({ token, trigger, session, account }) {
            if (trigger === "update") token.name = session.user.name
            if (account?.provider === "keycloak") {
                return { ...token, accessToken: account.access_token }
            }
            return token
        },
        async session({ session, token }) {
            if (token?.accessToken) session.accessToken = token.accessToken

            return session
        },
    },
    experimental: { enableWebAuthn: true },
})

declare module "next-auth" {
    interface Session {
        accessToken?: string
    }
}

declare module "next-auth/jwt" {
    interface JWT {
        accessToken?: string
    }
}
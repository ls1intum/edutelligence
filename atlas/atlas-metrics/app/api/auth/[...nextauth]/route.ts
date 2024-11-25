import NextAuth from "next-auth"
import GithubProvider from "next-auth/providers/github";

const providers = [
    GithubProvider({
        clientId: process.env.GITHUB_ID as string,
        clientSecret: process.env.GITHUB_SECRET as string,
    }),
]

const authOptions = {
    providers: providers,
};

const handler = NextAuth(authOptions)

export { handler as GET, handler as POST}
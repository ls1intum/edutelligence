import type { NextApiRequest, NextApiResponse } from "next"
import NextAuth from "next-auth"
import GithubProvider from "next-auth/providers/github";

export default async function auth(req: NextApiRequest, res: NextApiResponse) {

    const providers = [
        GithubProvider({
            clientId: process.env.GITHUB_ID!,
            clientSecret: process.env.GITHUB_SECRET!,
        }),
    ]

    const authOptions = {
        providers: providers,
    };

    return await NextAuth(req, res, authOptions)
}
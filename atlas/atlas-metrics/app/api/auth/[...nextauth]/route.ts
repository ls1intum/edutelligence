import NextAuth from "next-auth";
import GithubProvider from "next-auth/providers/github";

const providers = [
  GithubProvider({
    clientId: process.env.GITHUB_ID as string,
    clientSecret: process.env.GITHUB_SECRET as string,
  }),
];

const authOptions = {
  providers: providers,
  callbacks: {
    async session({ session, token }) {
      session.user.isAdmin = token.isAdmin || false;
      return session;
    },
    async jwt({ token, account, user }) {
      if (account?.access_token) {
        try {
          const admins = process.env.ADMINS?.split(",") || [];

          // Store admin status in the token
          token.isAdmin = admins.some((admin) => admin === token.email);
          // eslint-disable-next-line @typescript-eslint/no-unused-vars
        } catch (error) {
          token.isAdmin = false;
        }
      }
      return token;
    },
  },
};

const handler = NextAuth(authOptions);

export { handler as GET, handler as POST };

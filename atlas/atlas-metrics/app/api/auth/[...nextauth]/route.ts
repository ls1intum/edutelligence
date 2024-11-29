import GithubProvider from "next-auth/providers/github";
import NextAuth, { type DefaultSession, type DefaultUser, NextAuthOptions } from "next-auth";

// Extend the default User interface
declare module "next-auth" {
  interface Session {
    user: {
      /** Custom properties */
      isAdmin?: boolean;
    } & DefaultSession["user"];
  }

  interface User extends DefaultUser {
    isAdmin?: boolean;
  }
}

// Extend the default JWT interface
declare module "next-auth/jwt" {
  interface JWT {
    isAdmin?: boolean;
  }
}

const providers = [
  GithubProvider({
    clientId: process.env.GITHUB_ID as string,
    clientSecret: process.env.GITHUB_SECRET as string,
  }),
];

const authOptions: NextAuthOptions = {
  providers: providers,
  callbacks: {
    async session({ session, token }) {
      // Ensure `isAdmin` is included in the session
      session.user.isAdmin = token.isAdmin || false;
      return session;
    },
    async jwt({ token, account }) {
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

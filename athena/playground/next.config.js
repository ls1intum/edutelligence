/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  basePath: '/playground',
  // redirect from / to /playground for convenience when developing locally
  async redirects() {
    return [
      {
        source: '/',
        destination: '/playground',
        basePath: false,
        permanent: false,
      },
    ];
  }
};

module.exports = nextConfig;

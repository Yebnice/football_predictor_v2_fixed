import Script from "next/script";
import Layout from "../components/Layout";
import "../styles/globals.css";

export default function App({ Component, pageProps }) {
  return (
    <>
      <Script src="https://js.paystack.co/v1/inline.js" strategy="afterInteractive" />
      <Layout>
        <Component {...pageProps} />
      </Layout>
    </>
  );
}

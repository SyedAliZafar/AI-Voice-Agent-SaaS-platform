import { FeatureGrid } from "@/components/features/marketing/FeatureGrid";
import { Hero } from "@/components/features/marketing/Hero";
import { HowItWorks } from "@/components/features/marketing/HowItWorks";
import { MarketingFooter } from "@/components/features/marketing/MarketingFooter";
import { MarketingNav } from "@/components/features/marketing/MarketingNav";
import { Pricing } from "@/components/features/marketing/Pricing";

/** The public front door. Renders outside `(app)`, so it gets no sidebar or topbar.
 * Everything on it is static — the only way in is the "Open dashboard" link. */
export default function LandingPage() {
  return (
    <div className="bg-white">
      <MarketingNav />
      <main>
        <Hero />
        <HowItWorks />
        <FeatureGrid />
        <Pricing />
      </main>
      <MarketingFooter />
    </div>
  );
}

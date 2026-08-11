import { Prospect } from "@/lib/types";

export const UNSPECIFIED = "Unspecified";

/** Sorts labels alphabetically with the "Unspecified" bucket always last, so it
 * doesn't crowd out real values in either a group heading list or a filter dropdown.
 */
export function sortLabels(labels: string[]): string[] {
  return [...labels].sort((a, b) => {
    if (a === UNSPECIFIED) return 1;
    if (b === UNSPECIFIED) return -1;
    return a.localeCompare(b);
  });
}

export interface CityGroup {
  city: string;
  prospects: Prospect[];
}

export interface CategoryGroup {
  category: string;
  cities: CityGroup[];
  count: number;
}

export interface CountryGroup {
  country: string;
  categories: CategoryGroup[];
  count: number;
}

/** Country -> category -> city -> companies. All current data is UK-only, but this
 * makes no single-country assumption: grouping is driven entirely by whatever
 * values are present on the rows. Rows missing a level fall into "Unspecified"
 * rather than being dropped. Purely presentational — no backend change, works over
 * whatever /prospects already returned.
 */
export function groupProspects(prospects: Prospect[]): CountryGroup[] {
  const byCountry = new Map<string, Map<string, Map<string, Prospect[]>>>();

  for (const prospect of prospects) {
    const country = prospect.country || UNSPECIFIED;
    const category = prospect.category || UNSPECIFIED;
    const city = prospect.city || UNSPECIFIED;

    if (!byCountry.has(country)) byCountry.set(country, new Map());
    const byCategory = byCountry.get(country)!;

    if (!byCategory.has(category)) byCategory.set(category, new Map());
    const byCity = byCategory.get(category)!;

    if (!byCity.has(city)) byCity.set(city, []);
    byCity.get(city)!.push(prospect);
  }

  return sortLabels([...byCountry.keys()]).map((country) => {
    const byCategory = byCountry.get(country)!;
    const categories = sortLabels([...byCategory.keys()]).map((category) => {
      const byCity = byCategory.get(category)!;
      const cities = sortLabels([...byCity.keys()]).map((city) => ({
        city,
        prospects: byCity.get(city)!,
      }));
      return {
        category,
        cities,
        count: cities.reduce((sum, c) => sum + c.prospects.length, 0),
      };
    });
    return {
      country,
      categories,
      count: categories.reduce((sum, c) => sum + c.count, 0),
    };
  });
}

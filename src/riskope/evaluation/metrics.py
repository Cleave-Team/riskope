from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class CategoryMatch:
    tertiary: str
    in_predicted: bool
    in_ground_truth: bool


@dataclass
class CompanyEvaluation:
    ticker: str
    filing_date: str
    predicted_categories: set[str]
    ground_truth_categories: set[str]

    @property
    def true_positives(self) -> set[str]:
        return self.predicted_categories & self.ground_truth_categories

    @property
    def false_positives(self) -> set[str]:
        return self.predicted_categories - self.ground_truth_categories

    @property
    def false_negatives(self) -> set[str]:
        return self.ground_truth_categories - self.predicted_categories

    @property
    def precision(self) -> float:
        if not self.predicted_categories:
            return 0.0
        return len(self.true_positives) / len(self.predicted_categories)

    @property
    def recall(self) -> float:
        if not self.ground_truth_categories:
            return 0.0
        return len(self.true_positives) / len(self.ground_truth_categories)

    @property
    def f1(self) -> float:
        p, r = self.precision, self.recall
        if p + r == 0:
            return 0.0
        return 2 * p * r / (p + r)

    @property
    def jaccard(self) -> float:
        union = self.predicted_categories | self.ground_truth_categories
        if not union:
            return 0.0
        return len(self.true_positives) / len(union)


@dataclass
class AggregateEvaluation:
    companies: list[CompanyEvaluation] = field(default_factory=list)

    @property
    def macro_precision(self) -> float:
        if not self.companies:
            return 0.0
        return sum(c.precision for c in self.companies) / len(self.companies)

    @property
    def macro_recall(self) -> float:
        if not self.companies:
            return 0.0
        return sum(c.recall for c in self.companies) / len(self.companies)

    @property
    def macro_f1(self) -> float:
        if not self.companies:
            return 0.0
        return sum(c.f1 for c in self.companies) / len(self.companies)

    @property
    def micro_precision(self) -> float:
        total_tp = sum(len(c.true_positives) for c in self.companies)
        total_pred = sum(len(c.predicted_categories) for c in self.companies)
        if total_pred == 0:
            return 0.0
        return total_tp / total_pred

    @property
    def micro_recall(self) -> float:
        total_tp = sum(len(c.true_positives) for c in self.companies)
        total_gt = sum(len(c.ground_truth_categories) for c in self.companies)
        if total_gt == 0:
            return 0.0
        return total_tp / total_gt

    @property
    def micro_f1(self) -> float:
        p, r = self.micro_precision, self.micro_recall
        if p + r == 0:
            return 0.0
        return 2 * p * r / (p + r)

    @property
    def mean_jaccard(self) -> float:
        if not self.companies:
            return 0.0
        return sum(c.jaccard for c in self.companies) / len(self.companies)

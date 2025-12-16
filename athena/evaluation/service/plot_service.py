import matplotlib.pyplot as plt
import seaborn as sns
import os

from matplotlib.ticker import MultipleLocator


def plot_boxplot(df, x, y, hue, x_order, hue_order, title, ylabel, xlabel, legend_title, plot_path, filename):
    sns.boxplot(
        data=df,
        x=x,
        y=y,
        hue=hue,
        order=x_order,
        hue_order=hue_order,
        showmeans=True,
    )

    print(title)

    plt.ylabel(ylabel)
    plt.xlabel(xlabel)

    plt.gca().yaxis.set_major_locator(MultipleLocator(1))

    plt.legend(title=legend_title)

    plt.tight_layout()
    plt.grid(axis='y', linestyle='--', alpha=0.4)
    plt.show()
    plt.savefig(os.path.join(plot_path, filename))


def plot_feedback_type_metric(df, group, feedback_type_order, metric_order, plot_path):
    sns.boxplot(
        data=df,
        x='feedback_type',
        y='score',
        hue='metric',
        order=feedback_type_order,
        hue_order=metric_order,
        showmeans=True,
    )

    print(f'Assessment Scores by Feedback Type and Metric ({group}s):')

    plt.ylabel('Score')
    plt.xlabel('')

    plt.gca().yaxis.set_major_locator(MultipleLocator(1))

    plt.legend(title='Metric')

    plt.tight_layout()
    plt.grid(axis='y', linestyle='--', alpha=0.4)
    plt.show()
    plt.savefig(os.path.join(plot_path, f'{group}_feedback_type_metric_boxplot.png'))


def plot_metric_feedback_type(df, group, feedback_type_order, metric_order, plot_path):
    sns.boxplot(
        data=df,
        x='metric',
        y='score',
        hue='feedback_type',
        order=metric_order,
        hue_order=feedback_type_order,
        showmeans=True,
    )

    print(f'Assessment Scores by Metric and Feedback Type ({group}s):')

    plt.ylabel('Score')
    plt.xlabel('')

    plt.gca().yaxis.set_major_locator(MultipleLocator(1))

    plt.legend(title='Feedback Type')

    plt.tight_layout()
    plt.grid(axis='y', linestyle='--', alpha=0.4)
    plt.show()
    plt.savefig(os.path.join(plot_path, f'{group}_metric_feedback_type_boxplot.png'))

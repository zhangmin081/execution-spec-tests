"""
Test EIP-4844: Shard Blob Transactions (Excess Data Tests)
EIP: https://eips.ethereum.org/EIPS/eip-4844
"""
from dataclasses import dataclass
from typing import List, Mapping, Optional

from ethereum_test_forks import Fork, ShardingFork
from ethereum_test_tools import (
    Account,
    Block,
    BlockchainTest,
    Environment,
    Header,
    TestAddress,
    Transaction,
    test_from,
    to_address,
    to_hash_bytes,
)

REFERENCE_SPEC_GIT_PATH = "EIPS/eip-4844.md"
REFERENCE_SPEC_VERSION = "b33e063530f0a114635dd4f89d3cca90f8cac28f"

DATAHASH_GAS_COST = 3
MIN_DATA_GASPRICE = 1
DATA_GAS_PER_BLOB = 2**17
MAX_DATA_GAS_PER_BLOCK = 2**19
TARGET_DATA_GAS_PER_BLOCK = 2**18
MAX_BLOBS_PER_BLOCK = MAX_DATA_GAS_PER_BLOCK // DATA_GAS_PER_BLOB
TARGET_BLOBS_PER_BLOCK = TARGET_DATA_GAS_PER_BLOCK // DATA_GAS_PER_BLOB
DATA_GASPRICE_UPDATE_FRACTION = 2225652


def fake_exponential(factor: int, numerator: int, denominator: int) -> int:
    """
    Used to calculate the data gas cost.
    """
    i = 1
    output = 0
    numerator_accumulator = factor * denominator
    while numerator_accumulator > 0:
        output += numerator_accumulator
        numerator_accumulator = (numerator_accumulator * numerator) // (
            denominator * i
        )
        i += 1
    return output // denominator


def calc_data_fee(tx: Transaction, excess_data_gas: int) -> int:
    """
    Calculate the data fee for a transaction.
    """
    return get_total_data_gas(tx) * get_data_gasprice(excess_data_gas)


def get_total_data_gas(tx: Transaction) -> int:
    """
    Calculate the total data gas for a transaction.
    """
    if tx.blob_versioned_hashes is None:
        return 0
    return DATA_GAS_PER_BLOB * len(tx.blob_versioned_hashes)


def get_data_gasprice_from_blobs(excess_blobs: int) -> int:
    """
    Calculate the data gas price from the excess blob count.
    """
    return fake_exponential(
        MIN_DATA_GASPRICE,
        excess_blobs * DATA_GAS_PER_BLOB,
        DATA_GASPRICE_UPDATE_FRACTION,
    )


def get_data_gasprice(excess_data_gas: int) -> int:
    """
    Calculate the data gas price from the excess.
    """
    return fake_exponential(
        MIN_DATA_GASPRICE,
        excess_data_gas,
        DATA_GASPRICE_UPDATE_FRACTION,
    )


def calc_excess_data_gas(parent_excess_data_gas: int, new_blobs: int) -> int:
    """
    Calculate the excess data gas for a block given the parent excess data gas
    and the number of blobs in the block.
    """
    consumed_data_gas = new_blobs * DATA_GAS_PER_BLOB
    if parent_excess_data_gas + consumed_data_gas < TARGET_DATA_GAS_PER_BLOCK:
        return 0
    else:
        return (
            parent_excess_data_gas
            + consumed_data_gas
            - TARGET_DATA_GAS_PER_BLOCK
        )


@dataclass(kw_only=True)
class ExcessDataGasCalcTestCase:
    """
    Test case generator class for the correct excess data gas calculation.
    """

    parent_excess_blobs: int
    blobs: int
    block_base_fee: int = 7

    def generate(self) -> BlockchainTest:
        """
        Generate the test case.
        """
        parent_excess_data_gas = self.parent_excess_blobs * DATA_GAS_PER_BLOB
        env = Environment(excess_data_gas=parent_excess_data_gas)

        destination_account = to_address(0x100)

        excess_data_gas = calc_excess_data_gas(
            parent_excess_data_gas=parent_excess_data_gas,
            new_blobs=self.blobs,
        )
        data_gasprice = get_data_gasprice(
            excess_data_gas=parent_excess_data_gas
        )
        tx_value = 1
        tx_gas = 21000
        fee_per_gas = self.block_base_fee
        data_cost = data_gasprice * DATA_GAS_PER_BLOB * self.blobs
        tx_exact_cost = (tx_gas * fee_per_gas) + tx_value + data_cost
        pre = {
            TestAddress: Account(balance=tx_exact_cost),
        }

        if self.blobs > 0:
            tx = Transaction(
                ty=5,
                nonce=0,
                to=destination_account,
                value=tx_value,
                gas_limit=tx_gas,
                max_fee_per_gas=fee_per_gas,
                max_priority_fee_per_gas=0,
                max_fee_per_data_gas=data_gasprice,
                access_list=[],
                blob_versioned_hashes=[
                    to_hash_bytes(x) for x in range(self.blobs)
                ],
            )
        else:
            tx = Transaction(
                ty=2,
                nonce=0,
                to=destination_account,
                value=tx_value,
                gas_limit=tx_gas,
                max_fee_per_gas=fee_per_gas,
                max_priority_fee_per_gas=0,
                access_list=[],
            )

        return BlockchainTest(
            pre=pre,
            post={destination_account: Account(balance=1)},
            blocks=[Block(txs=[tx])],
            genesis_environment=env,
            tag=f"start_excess_data_gas_{hex(parent_excess_data_gas)}"
            + f"_blobs_{self.blobs}_"
            + f"expected_excess_data_gas_{excess_data_gas}",
        )


@test_from(fork=ShardingFork)
def test_excess_data_gas_calc(_: Fork):
    """
    Test calculation of the excess_data_gas increase/decrease across multiple
    blocks with and without blobs.
    """
    test_cases: List[ExcessDataGasCalcTestCase] = [
        # Result excess data gas zero, included data blob txs cost > 0
        ExcessDataGasCalcTestCase(
            parent_excess_blobs=TARGET_BLOBS_PER_BLOCK - 1,
            blobs=0,
        ),
        # Result excess data gas zero, included data blob txs cost 0
        ExcessDataGasCalcTestCase(
            parent_excess_blobs=0,
            blobs=TARGET_BLOBS_PER_BLOCK - 1,
        ),
        # Result excess data gas target, included data blob txs cost 0
        ExcessDataGasCalcTestCase(
            parent_excess_blobs=0,
            blobs=TARGET_BLOBS_PER_BLOCK,
        ),
        # Excess data gas result is max - target, included data blob txs cost 0
        ExcessDataGasCalcTestCase(
            parent_excess_blobs=0,
            blobs=MAX_BLOBS_PER_BLOCK,
        ),
        # Included data blob txs cost = 2
        ExcessDataGasCalcTestCase(
            parent_excess_blobs=12,
            blobs=1,
        ),
        # Included data blob txs cost = 1
        ExcessDataGasCalcTestCase(
            parent_excess_blobs=11,
            blobs=TARGET_BLOBS_PER_BLOCK + 1,
        ),
        # Included data blob txs cost < 2^32
        ExcessDataGasCalcTestCase(
            parent_excess_blobs=376,
            blobs=TARGET_BLOBS_PER_BLOCK + 1,
        ),
        # Included data blob txs cost > 2^32
        ExcessDataGasCalcTestCase(
            parent_excess_blobs=377,
            blobs=1,
        ),
        # Included data blob txs cost < 2^64
        ExcessDataGasCalcTestCase(
            parent_excess_blobs=753,
            blobs=TARGET_BLOBS_PER_BLOCK + 1,
        ),
        # Included data blob txs cost > 2^64
        ExcessDataGasCalcTestCase(
            parent_excess_blobs=754,
            blobs=1,
        ),
    ]

    for tc in test_cases:
        yield tc.generate()


@dataclass(kw_only=True)
class InvalidExcessDataGasInHeaderTestCase:
    """
    Test case generator for invalid excess_data_gas in header.
    """

    new_blobs: int
    header_excess_data_gas: Optional[int] = None
    header_excess_blobs_delta: Optional[int] = None
    parent_excess_blobs: int = 10

    def generate(self) -> BlockchainTest:
        """
        Generate the test case.
        """
        env = Environment(
            excess_data_gas=self.parent_excess_blobs * DATA_GAS_PER_BLOB,
        )

        pre = {
            TestAddress: Account(balance=10**40),
        }

        # All blocks are invalid in this type of test, no state modifications
        post: Mapping[str, Account] = {}

        parent_excess_data_gas = self.parent_excess_blobs * DATA_GAS_PER_BLOB

        correct_excess_data_gas = calc_excess_data_gas(
            parent_excess_data_gas=parent_excess_data_gas,
            new_blobs=self.new_blobs,
        )

        if self.header_excess_blobs_delta is not None:
            if self.header_excess_data_gas is not None:
                raise Exception("test case is badly formatted")
            self.header_excess_data_gas = parent_excess_data_gas + (
                self.header_excess_blobs_delta * DATA_GAS_PER_BLOB
            )
        if self.header_excess_data_gas is None:
            raise Exception("test case is badly formatted")

        if self.header_excess_data_gas == correct_excess_data_gas:
            raise Exception("invalid test case")

        if self.new_blobs == 0:
            # Send a normal type two tx instead
            tx = Transaction(
                ty=2,
                nonce=0,
                to=to_address(0x100),
                value=1,
                gas_limit=3000000,
                max_fee_per_gas=1000000,
                max_priority_fee_per_gas=10,
                access_list=[],
            )
        else:
            tx = Transaction(
                ty=5,
                nonce=0,
                to=to_address(0x100),
                value=1,
                gas_limit=3000000,
                max_fee_per_gas=1000000,
                max_priority_fee_per_gas=10,
                max_fee_per_data_gas=get_data_gasprice(
                    excess_data_gas=parent_excess_data_gas
                ),
                access_list=[],
                blob_versioned_hashes=[
                    to_hash_bytes(x) for x in range(self.new_blobs)
                ],
            )

        return BlockchainTest(
            pre=pre,
            post=post,
            blocks=[
                Block(
                    txs=[tx],
                    rlp_modifier=Header(
                        excess_data_gas=self.header_excess_data_gas
                    ),
                    exception="invalid excess data gas",
                )
            ],
            genesis_environment=env,
            tag=f"correct_{hex(correct_excess_data_gas)}_"
            + f"header_{hex(self.header_excess_data_gas)}",
        )


@test_from(fork=ShardingFork)
def test_invalid_excess_data_gas_in_header(_: Fork):
    """
    Test rejection of a block with invalid excess_data_gas in the header.
    """
    test_cases: List[InvalidExcessDataGasInHeaderTestCase] = []

    """
    Test case 1:
    - Initial excess of 10 blob data gas
    - 0 through 4 new blobs
    - Header excess data gas is either:
        - Unchanged
        - Reduced to zero
        - Reduced too much (-1 * DATA_GAS_PER_BLOB)
        - Increased too much (1 * DATA_GAS_PER_BLOB)
    """
    for blob_count in range(MAX_BLOBS_PER_BLOCK + 1):
        # Excess data gas cannot drop to zero because it can only decrease
        # TARGET_DATA_GAS_PER_BLOCK in one block
        test_cases.append(
            InvalidExcessDataGasInHeaderTestCase(
                new_blobs=blob_count,
                parent_excess_blobs=10,
                header_excess_data_gas=0,
            )
        )
        # Can never decrease more than TARGET_DATA_GAS_PER_BLOCK in a single
        # block
        test_cases.append(
            InvalidExcessDataGasInHeaderTestCase(
                new_blobs=blob_count,
                parent_excess_blobs=10,
                header_excess_blobs_delta=-(TARGET_BLOBS_PER_BLOCK + 1),
            )
        )
        # Can never increase more than TARGET_DATA_GAS_PER_BLOCK in a single
        # block
        test_cases.append(
            InvalidExcessDataGasInHeaderTestCase(
                new_blobs=blob_count,
                parent_excess_blobs=10,
                header_excess_blobs_delta=(TARGET_BLOBS_PER_BLOCK + 1),
            )
        )
        if blob_count != TARGET_BLOBS_PER_BLOCK:
            # Cannot remain unchanged if blobs != target blobs
            test_cases.append(
                InvalidExcessDataGasInHeaderTestCase(
                    new_blobs=blob_count,
                    parent_excess_blobs=10,
                    header_excess_blobs_delta=0,
                )
            )
        else:
            # Cannot change if blobs == target blobs
            test_cases.append(
                InvalidExcessDataGasInHeaderTestCase(
                    new_blobs=blob_count,
                    parent_excess_blobs=10,
                    header_excess_blobs_delta=-1,
                )
            )
            test_cases.append(
                InvalidExcessDataGasInHeaderTestCase(
                    new_blobs=blob_count,
                    parent_excess_blobs=10,
                    header_excess_blobs_delta=1,
                )
            )

    # Excess data gas cannot be a value lower than target, it must
    # wrap down to zero
    for blob_count in range(1, TARGET_BLOBS_PER_BLOCK):
        test_cases.append(
            InvalidExcessDataGasInHeaderTestCase(
                new_blobs=blob_count,
                parent_excess_blobs=0,
                header_excess_blobs_delta=blob_count,
            )
        )

    # New header excess data gas cannot be greater than 256-bits
    test_cases.append(
        InvalidExcessDataGasInHeaderTestCase(
            new_blobs=0,
            parent_excess_blobs=4346,
            header_excess_blobs_delta=TARGET_BLOBS_PER_BLOCK,
        )
    )

    for tc in test_cases:
        yield tc.generate()


def ignore_test_fork_transition_excess_data_gas_in_header(_: Fork):
    """
    Test excess_data_gas calculation in the header when the fork is activated.
    """
    # TODO!
    pass


@dataclass(kw_only=True)
class InvalidBlobTransactionTestCase:
    """
    Test case generator for invalid blob transactions.

    Transaction can be invalidated by modifying the following fields:
    - blobs_per_tx: Number of blobs in the transaction exceeds max blobs
    - tx_max_data_gas_cost: Transaction max_fee_per_data_gas is too low
    - tx_count: Number of transactions times blobs_per_tx exceeds max blobs
    """

    tag: str
    parent_excess_blobs: int
    blobs_per_tx: int
    tx_error: str
    tx_count: int = 1
    tx_max_data_gas_cost: Optional[int] = None
    account_balance_modifier: int = 0
    block_base_fee: int = 7

    def generate(self) -> BlockchainTest:
        """
        Generate the test case.
        """
        parent_excess_data_gas = self.parent_excess_blobs * DATA_GAS_PER_BLOB
        env = Environment(excess_data_gas=parent_excess_data_gas)

        destination_account = to_address(0x100)

        data_gasprice = get_data_gasprice(
            excess_data_gas=parent_excess_data_gas
        )

        total_account_minimum_balance = 0

        tx_value = 1
        tx_gas = 21000
        fee_per_gas = self.block_base_fee
        data_cost = data_gasprice * DATA_GAS_PER_BLOB * self.blobs_per_tx
        tx_exact_cost = (tx_gas * fee_per_gas) + tx_value + data_cost

        max_fee_per_data_gas = (
            self.tx_max_data_gas_cost
            if self.tx_max_data_gas_cost is not None
            else data_gasprice
        )

        txs: List[Transaction] = []
        for tx_i in range(self.tx_count):
            tx = Transaction(
                ty=5,
                nonce=tx_i,
                to=destination_account,
                value=tx_value,
                gas_limit=tx_gas,
                max_fee_per_gas=fee_per_gas,
                max_priority_fee_per_gas=0,
                max_fee_per_data_gas=max_fee_per_data_gas,
                access_list=[],
                blob_versioned_hashes=[
                    to_hash_bytes(x) for x in range(self.blobs_per_tx)
                ],
                error=self.tx_error if tx_i == (self.tx_count - 1) else None,
            )
            txs.append(tx)
            total_account_minimum_balance += tx_exact_cost

        pre = {
            TestAddress: Account(
                balance=total_account_minimum_balance
                + self.account_balance_modifier
            ),
        }

        return BlockchainTest(
            pre=pre,
            post={},
            blocks=[
                Block(
                    txs=txs,
                    exception=self.tx_error,
                )
            ],
            genesis_environment=env,
            tag=self.tag,
        )


@test_from(fork=ShardingFork)
def test_invalid_blob_txs(_: Fork):
    """
    Reject blocks with invalid blob txs due to:
        - The user cannot afford the data gas specified (but max_fee_per_gas
            would be enough for current block)
        - tx max_fee_per_data_gas is not enough
        - tx max_fee_per_data_gas is zero
        - blob count = 0 in type 5 transaction
        - blob count > MAX_BLOBS_PER_BLOCK in type 5 transaction
        - block blob count > MAX_BLOBS_PER_BLOCK
    """
    test_cases: List[InvalidBlobTransactionTestCase] = [
        InvalidBlobTransactionTestCase(
            tag="insufficient_max_fee_per_data_gas",
            parent_excess_blobs=15,  # data gas cost = 2
            tx_max_data_gas_cost=1,  # less than minimum
            tx_error="insufficient max fee per data gas",
            blobs_per_tx=1,
        ),
        InvalidBlobTransactionTestCase(
            tag="insufficient_balance_sufficient_fee",
            parent_excess_blobs=15,  # data gas cost = 1
            tx_max_data_gas_cost=100,  # > data gas cost
            account_balance_modifier=-1,
            tx_error="insufficient max fee per data gas",
            blobs_per_tx=1,
        ),
        InvalidBlobTransactionTestCase(
            tag="zero_max_fee_per_data_gas",
            parent_excess_blobs=0,  # data gas cost = 1
            tx_max_data_gas_cost=0,  # invalid value
            tx_error="insufficient max fee per data gas",
            blobs_per_tx=1,
        ),
        InvalidBlobTransactionTestCase(
            tag="blob_overflow",
            parent_excess_blobs=10,  # data gas cost = 1
            tx_error="too_many_blobs",
            blobs_per_tx=5,
        ),
        InvalidBlobTransactionTestCase(
            tag="multi_tx_blob_overflow",
            parent_excess_blobs=10,  # data gas cost = 1
            tx_error="too_many_blobs",
            tx_count=5,
            blobs_per_tx=1,
        ),
        # InvalidBlobTransactionTestCase(
        #     tag="blob_underflow",
        #     parent_excess_blobs=10,  # data gas cost = 1
        #     tx_error="too_few_blobs",
        #     blobs_per_tx=0,
        # ),
    ]

    for tc in test_cases:
        yield tc.generate()